# -*- coding: utf-8 -*-
"""
Extensão de sistemas administrativos para discord.py 2.x / Python 3.11+.
Integração: main.py deve criar `db_pool` (asyncpg.Pool) antes de carregar esta extensão.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
import json
import inspect
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("sistemas")

PURPLE = discord.Colour(0x7048BE)
BLUE = discord.Colour(0x477FA8)
RED = discord.Colour(0xC94C63)
GREEN = discord.Colour(0x48A878)
GOLD = discord.Colour(0xD4A64A)
EMOJI = {
    "alert": "<:emoji_33:1575019806636245012>",
    "github": "<:emoji_34:1575019961322053832>",
    "crown": "<:emoji_13:1556437078248656986>",
    "tools": "<:emoji_19:1556439034891599952>",
    "shield": "<:emoji_3:1556432452115898458>",
    "search": "<:emoji_30:157501938723534858>",
    "voice": "<:emoji_32:1575019682598092810>",
    "members": "<:emoji_17:1556438860798501016>",
    "ban": "<:emoji_10:1556436879086452766>",
    "web": "<:emoji_12:1556437008778534942>",
    "timer": "<:emoji_18:1556438970500522024>",
    "calendar": "<:emoji_20:1556439152625713264>",
    "id": "<:emoji_22:1556439311984103424>",
    "bell": "<:emoji_6:1556436410037305386>",
    "pin": "<:emoji_17:1556438912308617256>",
}

DEFAULTS = {
    "request_channel_id": None,
    "approved_channel_id": None,
    "denied_channel_id": None,
    "appeal_channel_id": None,
    "log_server_channel_id": None,
    "log_member_channel_id": None,
    "log_role_channel_id": None,
    "log_punishment_channel_id": None,
    "log_internal_channel_id": None,
    "reviewer_role_id": None,
    "staff_role_ids": [],
    "quarantine_role_id": None,
    "temp_voice_trigger_id": None,
    "temp_voice_category_id": None,
    "request_auto_types": [],
    "blue_banner_url": None,
    "backup_interval_hours": 24,
    "theme_image_url": None,
    "anti_raid_enabled": False,
    "anti_nuke_enabled": False,
    "anti_raid_threshold": 6,
    "anti_raid_window_seconds": 12,
    "welcome_channel_id": None,
    "welcome_message": "Bem-vindo(a), {member}, ao servidor {server}!",
    "autorole_id": None,
    "suggestion_channel_id": None,
    "report_channel_id": None,
    "trusted_admin_ids": [],
    "xp_enabled": False,
    "anti_spam_enabled": False,
    "anti_links_enabled": False,
}

def embed(title: str, description: str = "", color: discord.Colour = PURPLE) -> discord.Embed:
    e = discord.Embed(title=title, description=description, colour=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text="CENTRAL ADMINISTRATIVA  •  MODERAÇÃO & SEGURANÇA")
    return e

def clipped(value: Any, limit: int = 1000) -> str:
    value = str(value)
    return value if len(value) <= limit else value[:limit-1] + "…"

def valid_url(value: Optional[str]) -> bool:
    return value is None or bool(re.match(r"^https?://", value, re.I))

async def respond(inter: discord.Interaction, content: Optional[str] = None, *, em: Optional[discord.Embed] = None):
    if inter.response.is_done():
        await inter.followup.send(content=content, embed=em, ephemeral=True)
    else:
        await inter.response.send_message(content=content, embed=em, ephemeral=True)

def is_staff(member: discord.Member, cfg: dict) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    allowed = set(cfg.get("staff_role_ids") or [])
    if cfg.get("reviewer_role_id"):
        allowed.add(cfg["reviewer_role_id"])
    return any(r.id in allowed for r in member.roles)

def target_hierarchy(actor: discord.Member, target: discord.Member, bot_member: discord.Member):
    if actor.id == target.id:
        return False, "Você não pode aplicar punições em si mesmo."
    if target.id == actor.guild.owner_id:
        return False, "Não é possível moderar o proprietário do servidor."
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return False, "O cargo do acusado é igual ou superior ao seu."
    if target.top_role >= bot_member.top_role:
        return False, "O cargo do acusado é igual ou superior ao cargo do bot."
    return True, ""

class PunishmentRequestModal(discord.ui.Modal, title="Nova solicitação de punição"):
    accused_id = discord.ui.TextInput(label="ID do acusado", placeholder="ID numérico do Discord", min_length=17, max_length=20)
    punishment = discord.ui.TextInput(label="Punição solicitada", placeholder="warn, mute 60, kick, ban ou quarentena", max_length=20)
    reason = discord.ui.TextInput(label="Motivo detalhado", style=discord.TextStyle.paragraph, min_length=5, max_length=1500)
    occurred = discord.ui.TextInput(label="Data do ocorrido", placeholder="DD/MM/AAAA ou data aproximada", max_length=50)
    witnesses = discord.ui.TextInput(label="Testemunhas (opcional)", required=False, max_length=500)

    async def on_submit(self, inter: discord.Interaction):
        cog = inter.client.get_cog("Systems")
        if not cog:
            return await respond(inter, "Sistema indisponível.")
        if not self.accused_id.value.isdigit():
            return await respond(inter, "O ID precisa conter apenas números.")
        raw_kind = self.punishment.value.lower().strip()
        parts = raw_kind.replace(":", " ").split()
        kind = parts[0] if parts else ""
        aliases = {"advertencia":"warn", "advertência":"warn", "banimento":"ban", "expulsao":"kick", "expulsão":"kick"}
        kind = aliases.get(kind, kind)
        duration = None
        if kind == "mute" and len(parts) > 1 and parts[1].isdigit():
            duration = int(parts[1])
        if kind not in {"warn", "mute", "kick", "ban", "quarentena"}:
            return await respond(inter, "Punição inválida. Use warn, mute, kick, ban ou quarentena.")
        if kind == "mute" and (duration is None or not 1 <= duration <= 40320):
            return await respond(inter, "Para mute, informe também os minutos no campo punição. Exemplo: mute 60.")
        await cog.create_request(inter, int(self.accused_id.value), kind, self.reason.value.strip(), self.occurred.value.strip(), self.witnesses.value.strip() or None, None, duration)

class AppealModal(discord.ui.Modal, title="Solicitar revisão de punição"):
    case_id = discord.ui.TextInput(label="Número da punição", placeholder="Ex.: 124", max_length=20)
    explanation = discord.ui.TextInput(label="Por que deseja recorrer?", style=discord.TextStyle.paragraph, min_length=10, max_length=1500)
    evidence = discord.ui.TextInput(label="Links de provas (opcional)", required=False, max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        cog = inter.client.get_cog("Systems")
        if not cog:
            return await respond(inter, "Sistema indisponível.")
        if not self.case_id.value.isdigit():
            return await respond(inter, "Informe o número da punição.")
        await cog.create_appeal(inter, int(self.case_id.value), self.explanation.value.strip(), self.evidence.value.strip() or None)

class PunishmentPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Solicitar punição", emoji="⚖️", style=discord.ButtonStyle.primary, custom_id="sistemas:v2:request")
    async def request(self, inter: discord.Interaction, button: discord.ui.Button):
        cfg = await inter.client.get_cog("Systems").get_config(inter.guild.id)
        if not is_staff(inter.user, cfg):
            return await respond(inter, "Você não possui autorização para solicitar punições.")
        await inter.response.send_modal(PunishmentRequestModal())

    @discord.ui.button(label="Solicitar revisão", emoji="📨", style=discord.ButtonStyle.secondary, custom_id="sistemas:v2:appeal")
    async def appeal(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.send_modal(AppealModal())

class DecisionView(discord.ui.View):
    def __init__(self, request_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.request_id = request_id

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        cog = inter.client.get_cog("Systems")
        cfg = await cog.get_config(inter.guild.id)
        if not isinstance(inter.user, discord.Member) or not is_staff(inter.user, cfg):
            await respond(inter, "Você não tem permissão para analisar solicitações.")
            return False
        return True

    def _request_id(self, inter: discord.Interaction) -> int:
        title = inter.message.embeds[0].title if inter.message and inter.message.embeds else ""
        match = re.search(r"Solicitação\s*#([0-9]+)", title, re.I)
        if not match:
            raise ValueError("Não foi possível identificar a solicitação.")
        return int(match.group(1))

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.success, custom_id="sistemas:v2:decision:approve")
    async def approve(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.client.get_cog("Systems").decide_request(inter, self._request_id(inter), "approved")

    @discord.ui.button(label="Negar", emoji="❌", style=discord.ButtonStyle.danger, custom_id="sistemas:v2:decision:reject")
    async def reject(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.client.get_cog("Systems").decide_request(inter, self._request_id(inter), "denied")

    @discord.ui.button(label="Aplicar manualmente", emoji="🛠️", style=discord.ButtonStyle.secondary, custom_id="sistemas:v2:decision:manual")
    async def manual(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.client.get_cog("Systems").decide_request(inter, self._request_id(inter), "manual")


class ReportModal(discord.ui.Modal, title="Registrar denúncia"):
    subject = discord.ui.TextInput(label="Membro denunciado (ID)", placeholder="ID numérico", min_length=17, max_length=20)
    reason = discord.ui.TextInput(label="Relato detalhado", style=discord.TextStyle.paragraph, min_length=10, max_length=1800)
    evidence = discord.ui.TextInput(label="Links de provas (opcional)", required=False, max_length=1000)

    async def on_submit(self, inter: discord.Interaction):
        cog = inter.client.get_cog("Systems")
        if not cog: return await respond(inter, "O sistema de denúncias está indisponível.")
        if not self.subject.value.isdigit(): return await respond(inter, "Informe um ID válido.")
        await cog.create_report(inter, int(self.subject.value), self.reason.value.strip(), self.evidence.value.strip() or None)


class ReportPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar denúncia", emoji="🛡️", style=discord.ButtonStyle.primary, custom_id="sistemas:v3:report")
    async def report(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.send_modal(ReportModal())



class AppealDecisionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _appeal_id(self, inter: discord.Interaction) -> int:
        title = inter.message.embeds[0].title if inter.message and inter.message.embeds else ""
        match = re.search(r"Recurso\s*[•#]*\s*#?([0-9]+)", title, re.I)
        if not match: raise ValueError("Não foi possível identificar o recurso.")
        return int(match.group(1))

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        cog = inter.client.get_cog("Systems")
        cfg = await cog.get_config(inter.guild.id)
        if not isinstance(inter.user, discord.Member) or not is_staff(inter.user, cfg):
            await respond(inter, "Você não tem permissão para analisar recursos.")
            return False
        return True

    @discord.ui.button(label="Aprovar recurso", emoji="✅", style=discord.ButtonStyle.success, custom_id="sistemas:v3:appeal:approve")
    async def approve(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.client.get_cog("Systems").decide_appeal(inter, self._appeal_id(inter), "approved")

    @discord.ui.button(label="Negar recurso", emoji="❌", style=discord.ButtonStyle.danger, custom_id="sistemas:v3:appeal:reject")
    async def reject(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.client.get_cog("Systems").decide_appeal(inter, self._appeal_id(inter), "denied")


class Systems(commands.Cog):
    def __init__(self, bot: commands.Bot, pool: asyncpg.Pool):
        self.bot, self.pool = bot, pool
        self._voice_locks: dict[int, asyncio.Lock] = {}
        self._join_windows = defaultdict(deque)
        self._message_windows = defaultdict(deque)
        self.backup_loop.start()

    async def cog_load(self):
        await self.create_schema()
        self.bot.add_view(PunishmentPanel())
        self.bot.add_view(ReportPanel())
        rows = await self.pool.fetch("SELECT id, review_message_id FROM sistemas_requests WHERE status='pending' AND review_message_id IS NOT NULL")
        for row in rows:
            self.bot.add_view(DecisionView(), message_id=row["review_message_id"])
        appeals = await self.pool.fetch("SELECT id, review_message_id FROM sistemas_appeals WHERE status='pending' AND review_message_id IS NOT NULL")
        for row in appeals:
            self.bot.add_view(AppealDecisionView(), message_id=row["review_message_id"])

    def cog_unload(self):
        self.backup_loop.cancel()

    async def create_schema(self):
        queries = [
        """CREATE TABLE IF NOT EXISTS sistemas_config(guild_id BIGINT PRIMARY KEY, data JSONB NOT NULL DEFAULT '{}'::jsonb, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_cases(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),active BOOLEAN NOT NULL DEFAULT TRUE)""",
        """CREATE TABLE IF NOT EXISTS sistemas_requests(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,requester_id BIGINT NOT NULL,target_id BIGINT NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,occurred TEXT,witnesses TEXT,evidence_url TEXT,evidence_attachment_url TEXT,duration_minutes INTEGER,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,decision_reason TEXT,review_message_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS sistemas_appeals(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,case_id BIGINT NOT NULL,appellant_id BIGINT NOT NULL,explanation TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_afk(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,reason TEXT,since TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))""",
        """CREATE TABLE IF NOT EXISTS sistemas_staff(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))""",
        """CREATE TABLE IF NOT EXISTS sistemas_temp_voice(channel_id BIGINT PRIMARY KEY,guild_id BIGINT NOT NULL,owner_id BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sistemas_backups(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_audit(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,actor_id BIGINT,action TEXT NOT NULL,details JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_reports(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,reporter_id BIGINT NOT NULL,target_id BIGINT NOT NULL,reason TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_suggestions(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_xp(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,xp BIGINT NOT NULL DEFAULT 0,level INTEGER NOT NULL DEFAULT 0,last_message_at TIMESTAMPTZ,PRIMARY KEY(guild_id,user_id))"""
        ]
        async with self.pool.acquire() as conn:
            for q in queries:
                await conn.execute(q)
            # Migração segura para bancos criados por versões anteriores.
            for q in [
                "ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS evidence_attachment_url TEXT",
                "ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS occurred TEXT",
                "ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS witnesses TEXT",
                "ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS review_message_id BIGINT",
                "ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS duration_minutes INTEGER",
                "ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS review_message_id BIGINT",
            ]:
                await conn.execute(q)

    async def get_config(self, guild_id: int) -> dict:
        row = await self.pool.fetchrow("SELECT data FROM sistemas_config WHERE guild_id=$1", guild_id)
        data = dict(DEFAULTS)
        if row and row["data"]:
            raw = row["data"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            data.update(dict(raw))
        return data

    async def set_config(self, guild_id: int, key: str, value: Any):
        if key not in DEFAULTS:
            raise ValueError("Configuração desconhecida")
        cfg = await self.get_config(guild_id)
        cfg[key] = value
        await self.pool.execute("""INSERT INTO sistemas_config(guild_id,data,updated_at) VALUES($1,$2::jsonb,NOW()) ON CONFLICT(guild_id) DO UPDATE SET data=EXCLUDED.data,updated_at=NOW()""", guild_id, json.dumps(cfg))

    async def resolve_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int) -> Optional[int]:
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                target = getattr(entry, "target", None)
                if getattr(target, "id", None) == target_id:
                    age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
                    if age <= 30 and entry.user:
                        return entry.user.id
        except (discord.Forbidden, discord.HTTPException):
            log.debug("Sem acesso ao audit log de %s em %s", action, guild.id)
        return None

    async def send_log(self, guild: discord.Guild, key: str, title: str, description: str, color=PURPLE):
        try:
            cfg = await self.get_config(guild.id)
            channel_id = cfg.get(key)
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel:
                e = embed(title, description, color)
                if valid_url(cfg.get("theme_image_url")) and cfg.get("theme_image_url"):
                    e.set_image(url=cfg["theme_image_url"])
                await channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            log.exception("Falha ao enviar log %s", key)

    async def audit(self, guild: discord.Guild, actor_id: Optional[int], action: str, details: dict, channel_key: str = "log_internal_channel_id", color=PURPLE):
        safe = {str(k): clipped(v, 700) for k, v in details.items() if v is not None}
        await self.pool.execute("INSERT INTO sistemas_audit(guild_id,actor_id,action,details) VALUES($1,$2,$3,$4::jsonb)", guild.id, actor_id, action, json.dumps(safe, ensure_ascii=False))
        body = "\n".join(f"**{k.replace('_',' ').title()}:** {v}" for k,v in safe.items()) or "Sem detalhes adicionais."
        if actor_id: body = f"**Responsável:** <@{actor_id}> (`{actor_id}`)\n" + body
        await self.send_log(guild, channel_key, f"{EMOJI['pin']} {action}", body, color)

    async def create_report(self, inter: discord.Interaction, target_id: int, reason: str, evidence: Optional[str]):
        if evidence and not valid_url(evidence): return await respond(inter, "O link de prova precisa começar com http:// ou https://.")
        cfg = await self.get_config(inter.guild.id)
        channel = inter.guild.get_channel(cfg.get("report_channel_id")) if cfg.get("report_channel_id") else None
        if channel is None: return await respond(inter, "O canal de denúncias ainda não foi configurado. Peça à administração para usar /config_canal.")
        report_id = await self.pool.fetchval("INSERT INTO sistemas_reports(guild_id,reporter_id,target_id,reason,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id", inter.guild.id, inter.user.id, target_id, reason, evidence)
        e = embed(f"{EMOJI['shield']} Denúncia • Protocolo #{report_id}", "Uma denúncia foi registrada e aguarda análise da equipe.")
        e.add_field(name="Denunciante", value=f"{inter.user.mention} (`{inter.user.id}`)", inline=False)
        e.add_field(name="Membro denunciado", value=f"<@{target_id}> (`{target_id}`)", inline=False)
        e.add_field(name="Relato", value=clipped(reason, 1000), inline=False)
        e.add_field(name="Provas", value=evidence or "Não anexadas", inline=False)
        e.add_field(name="Registro", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", inline=False)
        if cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        await channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await self.audit(inter.guild, inter.user.id, "Denúncia registrada", {"protocolo": report_id, "denunciado": target_id}, "log_internal_channel_id")
        await respond(inter, f"Sua denúncia foi registrada com o protocolo **#{report_id}**. A equipe analisará o relato.")

    async def notify_dm(self, user: discord.abc.User, guild: discord.Guild, action: str, reason: str, case_id: int, expires=None):
        titles = {"ban":"⛔ Você foi banido","kick":"👢 Você foi expulso","mute":"🔇 Você recebeu um mute","quarentena":"🔒 Você foi colocado em quarentena","warn":"⚠️ Você recebeu uma advertência","hackban":"⛔ Seu ID foi banido"}
        e = embed(titles.get(action, "Aviso de moderação"), f"Você recebeu uma medida administrativa em **{guild.name}**.", RED if action in {"ban","kick","hackban"} else PURPLE)
        e.add_field(name="Punição", value=action.upper(), inline=True)
        e.add_field(name="Registro", value=f"#{case_id}", inline=True)
        e.add_field(name="Motivo", value=clipped(reason, 900), inline=False)
        if expires:
            e.add_field(name="Duração", value=f"Até <t:{int(expires.timestamp())}:F>", inline=False)
        e.add_field(name="Revisão", value="Use o painel de revisão do servidor ou contate a equipe responsável. A punição não é removida automaticamente ao recorrer.", inline=False)
        cfg = await self.get_config(guild.id)
        if cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        try:
            await user.send(embed=e)
        except (discord.Forbidden, discord.HTTPException):
            await self.send_log(guild, "log_internal_channel_id", "DM não entregue", f"Não foi possível enviar DM para `{user.id}` sobre o caso `#{case_id}`.", GOLD)

    async def add_case(self, guild: discord.Guild, user_id: int, moderator_id: int, action: str, reason: str, expires=None) -> int:
        case_id = await self.pool.fetchval("""INSERT INTO sistemas_cases(guild_id,user_id,moderator_id,action,reason,expires_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id""", guild.id,user_id,moderator_id,action,reason,expires)
        await self.send_log(guild, "log_punishment_channel_id", f"Registro de punição • {action}", f"Caso `#{case_id}`\nMembro: <@{user_id}> (`{user_id}`)\nResponsável: <@{moderator_id}>\nMotivo: {reason}")
        return case_id

    async def create_request(self, inter, target_id: int, kind: str, reason: str, occurred: str, witnesses: Optional[str], attachment: Optional[discord.Attachment], duration_minutes: Optional[int] = None):
        cfg = await self.get_config(inter.guild.id)
        member = inter.guild.get_member(target_id)
        user = member or await self.bot.fetch_user(target_id)
        channel_id = cfg.get("request_channel_id")
        channel = inter.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return await respond(inter, "O canal de solicitações ainda não foi configurado. Peça à administração para definir /config_canal.")
        attachment_url = attachment.url if attachment else None
        request_id = await self.pool.fetchval("""INSERT INTO sistemas_requests(guild_id,requester_id,target_id,kind,reason,occurred,witnesses,evidence_attachment_url,duration_minutes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""", inter.guild.id,inter.user.id,target_id,kind,reason,occurred,witnesses,attachment_url,duration_minutes)
        e = embed(f"⚖️ CENTRAL DE ANÁLISE • SOLICITAÇÃO #{request_id}", "Uma nova solicitação disciplinar foi protocolada. Revise os dados, as evidências e o histórico antes de tomar uma decisão.")
        if valid_url(cfg.get("theme_image_url")) and cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        e.add_field(name="Solicitante", value=f"{inter.user} (`{inter.user.id}`)", inline=False)
        e.add_field(name="Acusado", value=f"{user} (`{target_id}`)", inline=False)
        e.add_field(name="Punição", value=kind.upper(), inline=True)
        e.add_field(name="Data do ocorrido", value=occurred or "Não informada", inline=True)
        e.add_field(name="Data da solicitação", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", inline=False)
        e.add_field(name="Motivo", value=clipped(reason,1000), inline=False)
        e.add_field(name="Testemunhas", value=clipped(witnesses or "Não informadas",500), inline=False)
        if attachment_url:
            e.add_field(name="Prova anexada", value=attachment_url, inline=False)
        try:
            msg = await channel.send(embed=e, view=DecisionView(request_id), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return await respond(inter, "Não consegui publicar a solicitação. Confira as permissões do bot no canal.")
        await self.pool.execute("UPDATE sistemas_requests SET review_message_id=$1 WHERE id=$2", msg.id, request_id)
        self.bot.add_view(DecisionView(request_id), message_id=msg.id)
        await self.send_log(inter.guild, "log_internal_channel_id", "Solicitação criada", f"Solicitação `#{request_id}` criada por {inter.user.mention}.")
        await respond(inter, f"Sua solicitação **#{request_id}** foi encaminhada para análise.")

    async def decide_request(self, inter: discord.Interaction, request_id: int, decision: str):
        row = await self.pool.fetchrow("SELECT * FROM sistemas_requests WHERE id=$1 AND guild_id=$2", request_id, inter.guild.id)
        if not row:
            return await respond(inter, "Solicitação não encontrada.")
        if row["status"] != "pending":
            return await respond(inter, "Essa solicitação já foi analisada.")
        cfg = await self.get_config(inter.guild.id)
        kind = row["kind"]
        auto_types = set(cfg.get("request_auto_types") or [])
        should_apply = decision == "manual" or (decision == "approved" and kind in auto_types)
        if decision == "denied":
            await self.pool.execute("UPDATE sistemas_requests SET status='denied',reviewer_id=$1,decided_at=NOW(),decision_reason='Negada pela equipe' WHERE id=$2", inter.user.id, request_id)
            ch = inter.guild.get_channel(cfg.get("denied_channel_id")) if cfg.get("denied_channel_id") else None
            if ch:
                result_embed = embed(f"❌ SOLICITAÇÃO #{request_id} • NEGADA", f"**Acusado:** <@{row['target_id']}>\n**Solicitante:** <@{row['requester_id']}>\n**Analisada por:** {inter.user.mention}\n\nA equipe concluiu a análise e registrou a decisão de não aprovar o pedido.", RED)
                if cfg.get("theme_image_url"): result_embed.set_image(url=cfg["theme_image_url"])
                await ch.send(embed=result_embed)
            await inter.response.edit_message(embed=embed(f"Solicitação #{request_id} • NEGADA", "A solicitação foi recusada.", RED), view=None)
            return
        if decision == "approved" and not should_apply:
            await self.pool.execute("UPDATE sistemas_requests SET status='approved_manual',reviewer_id=$1,decided_at=NOW(),decision_reason='Aprovada; aplicação manual configurada' WHERE id=$2", inter.user.id, request_id)
            ch = inter.guild.get_channel(cfg.get("approved_channel_id")) if cfg.get("approved_channel_id") else None
            if ch:
                result_embed = embed(f"🟣 SOLICITAÇÃO #{request_id} • APROVADA PARA APLICAÇÃO MANUAL", f"**Punição:** {kind.upper()}\n**Acusado:** <@{row['target_id']}>\n**Analisada por:** {inter.user.mention}\n\nA aplicação automática está desativada para este tipo. Um moderador autorizado deve executar `/aplicar_solicitacao {request_id}` após conferir o pedido.", GOLD)
                if cfg.get("theme_image_url"): result_embed.set_image(url=cfg["theme_image_url"])
                await ch.send(embed=result_embed)
            await inter.response.edit_message(embed=embed(f"Solicitação #{request_id} • APROVADA", "Aprovada. A aplicação deverá ser feita manualmente, conforme a configuração deste servidor.", GOLD), view=None)
            return
        try:
            await self.apply_punishment(inter.guild, row["target_id"], inter.user, kind, row["reason"], row["duration_minutes"])
        except Exception as exc:
            return await respond(inter, f"Não foi possível aplicar a punição: {clipped(exc,250)}. A solicitação continua pendente para correção manual.")
        await self.pool.execute("UPDATE sistemas_requests SET status='approved',reviewer_id=$1,decided_at=NOW(),decision_reason=$3 WHERE id=$2", inter.user.id, request_id, "Aplicada manualmente" if decision == "manual" else "Aplicada automaticamente")
        ch = inter.guild.get_channel(cfg.get("approved_channel_id")) if cfg.get("approved_channel_id") else None
        if ch:
            result_embed = embed(f"✅ SOLICITAÇÃO #{request_id} • APROVADA", f"**Punição:** {kind.upper()}\n**Acusado:** <@{row['target_id']}>\n**Analisada por:** {inter.user.mention}\n**Execução:** {'manual' if decision == 'manual' else 'automática'}\n\nA medida foi aplicada e vinculada ao histórico administrativo do servidor.", GREEN)
            if cfg.get("theme_image_url"): result_embed.set_image(url=cfg["theme_image_url"])
            await ch.send(embed=result_embed)
        await inter.response.edit_message(embed=embed(f"Solicitação #{request_id} • APROVADA", "Punição aplicada e registrada.", GREEN), view=None)

    async def apply_punishment(self, guild: discord.Guild, target_id: int, moderator: discord.Member, kind: str, reason: str, duration_minutes: Optional[int]):
        member = guild.get_member(target_id)
        bot_member = guild.me
        expires = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes) if duration_minutes else None
        if kind == "hackban":
            if not moderator.guild_permissions.ban_members and not moderator.guild_permissions.administrator:
                raise ValueError("Você precisa da permissão Banir membros para usar hackban.")
            if not guild.me or not guild.me.guild_permissions.ban_members:
                raise ValueError("O bot precisa da permissão Banir membros.")
            if target_id == moderator.id or target_id == guild.owner_id:
                raise ValueError("Você não pode aplicar hackban nesse ID.")
            await guild.ban(discord.Object(id=target_id), reason=f"{moderator}: {reason}", delete_message_seconds=0)
            case = await self.add_case(guild,target_id,moderator.id,kind,reason)
            try: user=await self.bot.fetch_user(target_id); await self.notify_dm(user,guild,kind,reason,case)
            except discord.HTTPException: pass
            return case
        if not member:
            raise ValueError("O acusado não está no servidor. Use hackban para banir um ID externo.")
        ok, why = target_hierarchy(moderator, member, bot_member)
        if not ok: raise ValueError(why)
        if kind == "ban":
            await guild.ban(member, reason=f"{moderator}: {reason}", delete_message_seconds=0)
        elif kind == "kick":
            await member.kick(reason=f"{moderator}: {reason}")
        elif kind == "mute":
            if not duration_minutes: raise ValueError("Mute exige duração em minutos.")
            await member.timeout(timedelta(minutes=duration_minutes), reason=f"{moderator}: {reason}")
        elif kind == "warn":
            pass
        elif kind == "quarentena":
            cfg=await self.get_config(guild.id); role_id=cfg.get("quarantine_role_id")
            role=guild.get_role(role_id) if role_id else None
            if role is None:
                role=await guild.create_role(name="Quarentena", colour=discord.Colour(0x34303B), reason="Cargo automático do sistema de quarentena")
                await self.set_config(guild.id,"quarantine_role_id",role.id)
                for channel in guild.channels:
                    try:
                        await channel.set_permissions(role, view_channel=False, send_messages=False, connect=False)
                    except discord.Forbidden: pass
            # Não remove cargos existentes: isso destruiria a hierarquia e permissões legítimas do membro.
            await member.add_roles(role, reason=reason)
        else:
            raise ValueError("Tipo de punição desconhecido.")
        case=await self.add_case(guild,target_id,moderator.id,kind,reason,expires)
        await self.notify_dm(member,guild,kind,reason,case,expires)
        return case

    async def create_appeal(self, inter, case_id: int, explanation: str, evidence: Optional[str]):
        if not valid_url(evidence):
            return await respond(inter,"O link de prova precisa começar com http:// ou https://.")
        case=await self.pool.fetchrow("SELECT * FROM sistemas_cases WHERE id=$1 AND guild_id=$2 AND user_id=$3",case_id,inter.guild.id,inter.user.id)
        if not case: return await respond(inter,"Não encontrei uma punição sua com esse número neste servidor.")
        cfg=await self.get_config(inter.guild.id); channel=inter.guild.get_channel(cfg.get("appeal_channel_id")) if cfg.get("appeal_channel_id") else None
        if not channel: return await respond(inter,"O canal de revisão ainda não foi configurado. Seu recurso não foi gravado; peça à administração para configurar o canal.")
        appeal_id=await self.pool.fetchval("INSERT INTO sistemas_appeals(guild_id,case_id,appellant_id,explanation,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id",inter.guild.id,case_id,inter.user.id,explanation,evidence)
        e=embed(f"📨 CENTRAL DE REVISÃO • RECURSO #{appeal_id}",f"Foi recebido um pedido formal de revisão referente à punição `#{case_id}`. A decisão original permanece válida até análise da equipe.")
        if valid_url(cfg.get("theme_image_url")) and cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        e.add_field(name="Membro",value=f"{inter.user} (`{inter.user.id}`)",inline=False)
        e.add_field(name="Justificativa",value=clipped(explanation),inline=False)
        e.add_field(name="Provas",value=evidence or "Não informadas",inline=False)
        msg = await channel.send(embed=e, view=AppealDecisionView(), allowed_mentions=discord.AllowedMentions.none())
        await self.pool.execute("UPDATE sistemas_appeals SET review_message_id=$1 WHERE id=$2", msg.id, appeal_id)
        self.bot.add_view(AppealDecisionView(), message_id=msg.id)
        await respond(inter,f"Recurso **#{appeal_id}** enviado para análise. A punição continua ativa enquanto não houver decisão.")

    async def decide_appeal(self, inter: discord.Interaction, appeal_id: int, decision: str):
        row = await self.pool.fetchrow("SELECT * FROM sistemas_appeals WHERE id=$1 AND guild_id=$2", appeal_id, inter.guild.id)
        if not row: return await respond(inter, "Recurso não encontrado.")
        if row["status"] != "pending": return await respond(inter, "Este recurso já foi analisado.")
        await self.pool.execute("UPDATE sistemas_appeals SET status=$1,reviewer_id=$2 WHERE id=$3", decision, inter.user.id, appeal_id)
        case_note = "A revisão foi aprovada. A equipe deve executar a reversão da medida quando aplicável; o bot não desfaz automaticamente banimentos ou expulsões." if decision == "approved" else "A revisão foi negada. A punição original permanece conforme o registro."
        color = GREEN if decision == "approved" else RED
        title = "RECURSO APROVADO" if decision == "approved" else "RECURSO NEGADO"
        e = embed(f"📨 {title} • #{appeal_id}", case_note, color)
        e.add_field(name="Punição original", value=f"#{row['case_id']}", inline=True)
        e.add_field(name="Membro", value=f"<@{row['appellant_id']}>", inline=True)
        e.add_field(name="Responsável pela análise", value=inter.user.mention, inline=False)
        await inter.response.edit_message(embed=e, view=None)
        try:
            user = await self.bot.fetch_user(row["appellant_id"])
            await user.send(embed=e)
        except discord.HTTPException: pass
        await self.audit(inter.guild, inter.user.id, "Recurso analisado", {"recurso": appeal_id, "decisão": decision, "case_id": row["case_id"]}, "log_internal_channel_id", color)

    @app_commands.command(name="aplicar_solicitacao", description="Executa manualmente uma solicitação previamente aprovada.")
    async def apply_approved_request(self, inter: discord.Interaction, solicitacao_id: int):
        cfg = await self.get_config(inter.guild.id)
        if not is_staff(inter.user, cfg): return await respond(inter, "Você não tem autorização para aplicar solicitações.")
        row = await self.pool.fetchrow("SELECT * FROM sistemas_requests WHERE id=$1 AND guild_id=$2", solicitacao_id, inter.guild.id)
        if not row or row["status"] != "approved_manual": return await respond(inter, "Solicitação não encontrada ou não está aguardando aplicação manual.")
        try: case = await self.apply_punishment(inter.guild, row["target_id"], inter.user, row["kind"], row["reason"], row["duration_minutes"])
        except Exception as exc: return await respond(inter, f"Falha ao aplicar: {clipped(exc, 300)}")
        await self.pool.execute("UPDATE sistemas_requests SET status='approved',reviewer_id=$1,decided_at=NOW(),decision_reason='Aplicada manualmente após aprovação' WHERE id=$2", inter.user.id, solicitacao_id)
        await self.audit(inter.guild, inter.user.id, "Solicitação aprovada aplicada manualmente", {"solicitação": solicitacao_id, "caso": case}, "log_internal_channel_id", GREEN)
        await respond(inter, f"Solicitação **#{solicitacao_id}** aplicada. Caso de punição **#{case}**.")

    @app_commands.command(name="solicitar_punicao", description="Envia uma solicitação com prova em anexo opcional.")
    async def request_with_attachment(self, inter: discord.Interaction, id_acusado: str, tipo: str, motivo: str, data_ocorrido: str, testemunhas: Optional[str]=None, prova: Optional[discord.Attachment]=None, duracao_minutos: Optional[app_commands.Range[int,1,40320]]=None):
        cfg=await self.get_config(inter.guild.id)
        if not isinstance(inter.user, discord.Member) or not is_staff(inter.user,cfg):
            return await respond(inter,"Você não tem autorização para solicitar punições.")
        if not id_acusado.isdigit():
            return await respond(inter,"ID do acusado inválido.")
        kind=tipo.lower()
        if kind not in {"warn","mute","kick","ban","quarentena"}:
            return await respond(inter,"Tipo inválido. Use warn, mute, kick, ban ou quarentena.")
        if kind == "mute" and not duracao_minutos:
            return await respond(inter,"Mute exige a duração em minutos.")
        await self.create_request(inter,int(id_acusado),kind,motivo,data_ocorrido,testemunhas,prova,duracao_minutos)

    @app_commands.command(name="painel_punicoes", description="Publica o painel de solicitações de punição.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, inter: discord.Interaction, canal: discord.TextChannel):
        e=embed("⚖️ CENTRAL DE SOLICITAÇÕES", "Utilize esta central para protocolar pedidos de medida disciplinar ou solicitar revisão de uma punição. Preencha os campos com informações completas, descreva os fatos com clareza e apresente evidências sempre que possível. Cada pedido recebe um protocolo e será encaminhado à equipe responsável.")
        cfg = await self.get_config(inter.guild.id)
        if cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        await canal.send(embed=e,view=PunishmentPanel())
        await respond(inter,f"Painel publicado em {canal.mention}.")

    @app_commands.command(name="config_canal", description="Define os canais usados pelos sistemas.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Solicitações de punição",value="request_channel_id"),
        app_commands.Choice(name="Punições aprovadas",value="approved_channel_id"),
        app_commands.Choice(name="Punições negadas",value="denied_channel_id"),
        app_commands.Choice(name="Recursos / revisão manual",value="appeal_channel_id"),
        app_commands.Choice(name="Logs do servidor",value="log_server_channel_id"),
        app_commands.Choice(name="Logs de membros",value="log_member_channel_id"),
        app_commands.Choice(name="Logs de cargos",value="log_role_channel_id"),
        app_commands.Choice(name="Logs de punições",value="log_punishment_channel_id"),
        app_commands.Choice(name="Logs internos do bot",value="log_internal_channel_id"),
        app_commands.Choice(name="Denúncias",value="report_channel_id"),
        app_commands.Choice(name="Sugestões",value="suggestion_channel_id"),
        app_commands.Choice(name="Boas-vindas",value="welcome_channel_id"),
    ])
    async def config_channel(self, inter: discord.Interaction, tipo: app_commands.Choice[str], canal: discord.TextChannel):
        await self.set_config(inter.guild.id,tipo.value,canal.id)
        await respond(inter,f"Canal **{tipo.name}** definido para {canal.mention}.")

    @app_commands.command(name="config_punicao_automatica", description="Escolhe se um tipo será aplicado automaticamente após aprovação.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_auto_punishment(self, inter: discord.Interaction, tipo: str, automatico: bool):
        kind = tipo.lower().strip()
        if kind not in {"warn", "mute", "kick", "ban", "quarentena"}:
            return await respond(inter, "Tipo inválido. Use warn, mute, kick, ban ou quarentena.")
        cfg = await self.get_config(inter.guild.id)
        enabled = set(cfg.get("request_auto_types") or [])
        if automatico: enabled.add(kind)
        else: enabled.discard(kind)
        await self.set_config(inter.guild.id, "request_auto_types", sorted(enabled))
        await respond(inter, f"A aplicação de **{kind}** após aprovação foi {'ativada' if automatico else 'desativada'}. Tipos automáticos: {', '.join(sorted(enabled)) or 'nenhum'}.")

    @app_commands.command(name="config_revisores", description="Define o cargo autorizado a analisar punições e recursos.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_reviewers(self, inter: discord.Interaction, cargo: discord.Role):
        await self.set_config(inter.guild.id,"reviewer_role_id",cargo.id)
        await respond(inter,f"Cargo revisor definido: {cargo.mention}.")

    @app_commands.command(name="config_staff", description="Adiciona um cargo à lista automática da staff.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_staff(self, inter: discord.Interaction, cargo: discord.Role):
        cfg=await self.get_config(inter.guild.id); ids=set(cfg.get("staff_role_ids") or []); ids.add(cargo.id)
        await self.set_config(inter.guild.id,"staff_role_ids",list(ids))
        await respond(inter,f"Cargo {cargo.mention} adicionado à lista da staff.")

    @app_commands.command(name="lista_staff", description="Lista membros dos cargos staff configurados.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_list(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True,thinking=True)
        cfg=await self.get_config(inter.guild.id); ids=set(cfg.get("staff_role_ids") or [])
        if not ids: return await inter.followup.send("Configure cargos com `/config_staff`.",ephemeral=True)
        lines=[]
        for rid in ids:
            role=inter.guild.get_role(rid)
            if not role: continue
            members=role.members
            online=[m for m in members if m.status != discord.Status.offline]
            lines.append(f"**{role.name}** — {len(members)} membro(s), {len(online)} online\\n"+", ".join(m.display_name for m in members[:40]) if members else f"**{role.name}** — nenhum membro")
        await inter.followup.send(embed=embed("👥 Lista da equipe","\\n\\n".join(lines)[:4000] or "Nenhum cargo válido configurado."),ephemeral=True)

    @app_commands.command(name="punir", description="Aplica uma punição diretamente.")
    @app_commands.describe(tipo="warn, mute, kick, ban, quarentena ou hackban",duracao_minutos="Obrigatório para mute")
    async def punish(self, inter: discord.Interaction, tipo: str, id_membro: str, motivo: str, duracao_minutos: Optional[app_commands.Range[int,1,40320]]=None):
        cfg = await self.get_config(inter.guild.id)
        if not is_staff(inter.user, cfg): return await respond(inter, "Você não tem autorização para aplicar punições.")
        if not id_membro.isdigit(): return await respond(inter,"ID inválido.")
        kind=tipo.lower()
        if kind not in {"warn","mute","kick","ban","quarentena","hackban"}: return await respond(inter,"Tipo inválido.")
        try:
            case=await self.apply_punishment(inter.guild,int(id_membro),inter.user,kind,motivo,duracao_minutos)
        except (discord.Forbidden,discord.NotFound,discord.HTTPException,ValueError) as exc:
            return await respond(inter,f"Não foi possível aplicar: {clipped(exc,300)}")
        await respond(inter,f"Punição **{kind}** aplicada. Registro `#{case}`.")

    async def _prefix_punish(self, ctx: commands.Context, kind: str, target_id: int, reason: str):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("Use este comando dentro de um servidor.")
        cfg = await self.get_config(ctx.guild.id)
        required = {"ban": "ban_members", "hackban": "ban_members", "kick": "kick_members", "mute": "moderate_members", "warn": "moderate_members", "quarentena": "manage_roles"}.get(kind, "moderate_members")
        if not (is_staff(ctx.author, cfg) or getattr(ctx.author.guild_permissions, required, False)):
            return await ctx.reply(f"Você precisa da permissão **{required}** ou de um cargo staff autorizado.")
        try:
            case = await self.apply_punishment(ctx.guild, target_id, ctx.author, kind, reason, None)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError) as exc:
            return await ctx.reply(f"Não foi possível aplicar: {clipped(exc, 250)}")
        await ctx.reply(f"Punição **{kind}** aplicada. Registro `#{case}`.")

    @commands.command(name="ban")
    async def prefix_ban(self, ctx: commands.Context, membro: discord.Member, *, motivo: str="Sem motivo informado"):
        await self._prefix_punish(ctx, "ban", membro.id, motivo)

    @commands.command(name="kick")
    async def prefix_kick(self, ctx: commands.Context, membro: discord.Member, *, motivo: str="Sem motivo informado"):
        await self._prefix_punish(ctx, "kick", membro.id, motivo)

    @commands.command(name="warn")
    async def prefix_warn(self, ctx: commands.Context, membro: discord.Member, *, motivo: str="Sem motivo informado"):
        await self._prefix_punish(ctx, "warn", membro.id, motivo)

    @commands.command(name="quarentena")
    async def prefix_quarantine(self, ctx: commands.Context, membro: discord.Member, *, motivo: str="Sem motivo informado"):
        await self._prefix_punish(ctx, "quarentena", membro.id, motivo)

    @commands.command(name="hackban")
    async def prefix_hackban(self, ctx: commands.Context, id_membro: int, *, motivo: str="Sem motivo informado"):
        await self._prefix_punish(ctx, "hackban", id_membro, motivo)

    @commands.command(name="mute")
    async def prefix_mute(self, ctx: commands.Context, membro: discord.Member, minutos: int, *, motivo: str="Sem motivo informado"):
        if minutos < 1 or minutos > 40320:
            return await ctx.reply("A duração deve ficar entre 1 e 40320 minutos.")
        cfg = await self.get_config(ctx.guild.id)
        if not (ctx.author.guild_permissions.moderate_members or is_staff(ctx.author, cfg)):
            return await ctx.reply("Você não tem permissão para usar este comando.")
        try:
            case = await self.apply_punishment(ctx.guild, membro.id, ctx.author, "mute", motivo, minutos)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError) as exc:
            return await ctx.reply(f"Não foi possível aplicar: {clipped(exc, 250)}")
        await ctx.reply(f"Mute aplicado por {minutos} minuto(s). Registro `#{case}`.")

    @app_commands.command(name="clear_warn", description="Desativa advertências ativas de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def clear_warn(self, inter: discord.Interaction, membro: discord.Member, motivo: str):
        result=await self.pool.execute("UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND user_id=$2 AND action='warn' AND active=TRUE",inter.guild.id,membro.id)
        case=await self.add_case(inter.guild,membro.id,inter.user.id,"clear_warn",motivo)
        await respond(inter,f"Advertências ativas removidas. {result}. Registro `#{case}`.")

    @commands.command(name="clear_warn")
    async def prefix_clear_warn(self, ctx: commands.Context, membro: discord.Member, *, motivo: str="Limpeza de advertências"):
        cfg = await self.get_config(ctx.guild.id)
        if not (ctx.author.guild_permissions.moderate_members or is_staff(ctx.author, cfg)):
            return await ctx.reply("Você não tem permissão para usar este comando.")
        result = await self.pool.execute("UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND user_id=$2 AND action='warn' AND active=TRUE", ctx.guild.id, membro.id)
        case = await self.add_case(ctx.guild, membro.id, ctx.author.id, "clear_warn", motivo)
        await ctx.reply(f"Advertências ativas removidas. {result}. Registro `#{case}`.")

    @app_commands.command(name="historico_punicoes", description="Consulta o histórico de punições de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, inter: discord.Interaction, membro: discord.Member):
        rows=await self.pool.fetch("SELECT id,action,reason,moderator_id,created_at,active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15",inter.guild.id,membro.id)
        e=embed(f"Histórico • {membro}",f"Registros encontrados: {len(rows)}")
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['action']} • {'ativo' if r['active'] else 'inativo'}",value=clipped(f"{r['reason']}\\nResponsável: <@{r['moderator_id']}> • {r['created_at']:%d/%m/%Y %H:%M UTC}"),inline=False)
        await respond(inter,em=e)

    async def _join_afk_voice(self, guild: discord.Guild, member: discord.Member):
        if not member.voice or not member.voice.channel:
            raise ValueError("Entre em um canal de voz primeiro para chamar o bot.")
        channel = member.voice.channel
        vc = guild.voice_client
        if vc and vc.is_connected():
            await vc.move_to(channel)
            await vc.edit(self_deaf=True, self_mute=True)
        else:
            await channel.connect(self_deaf=True, self_mute=True)
        return channel

    @app_commands.command(name="afk", description="Coloca o bot na sua call e ativa seu status AFK.")
    async def afk(self, inter: discord.Interaction, motivo: Optional[str]="Ausente"):
        if not isinstance(inter.user, discord.Member):
            return await respond(inter, "Use este comando dentro de um servidor.")
        try:
            channel = await self._join_afk_voice(inter.guild, inter.user)
        except (ValueError, discord.HTTPException, discord.Forbidden) as exc:
            return await respond(inter, f"Não consegui entrar na call: {clipped(exc, 250)}")
        await self.pool.execute("INSERT INTO sistemas_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()",inter.guild.id,inter.user.id,motivo)
        await respond(inter, f"Estou na call **{channel.name}**, mutado e ensurdecido. Para me retirar, use `/afk_sair`.")

    @app_commands.command(name="afk_sair", description="Retira o bot do canal de voz.")
    async def afk_leave(self, inter: discord.Interaction):
        vc = inter.guild.voice_client if inter.guild else None
        if not vc or not vc.is_connected():
            return await respond(inter, "Não estou conectado a um canal de voz neste servidor.")
        await vc.disconnect(force=True)
        await respond(inter, "Saí do canal de voz.")

    @commands.group(name="afk", invoke_without_command=True)
    async def afk_prefix(self, ctx: commands.Context, *, motivo: str="Ausente"):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("Use este comando dentro de um servidor.")
        try:
            channel = await self._join_afk_voice(ctx.guild, ctx.author)
        except (ValueError, discord.HTTPException, discord.Forbidden) as exc:
            return await ctx.reply(f"Não consegui entrar na call: {clipped(exc, 250)}")
        await self.pool.execute("INSERT INTO sistemas_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()",ctx.guild.id,ctx.author.id,motivo)
        await ctx.reply(f"Estou na call **{channel.name}**, mutado e ensurdecido. Use `.afk sair` para me retirar.")

    @afk_prefix.command(name="sair")
    async def afk_prefix_leave(self, ctx: commands.Context):
        vc = ctx.guild.voice_client if ctx.guild else None
        if not vc or not vc.is_connected():
            return await ctx.reply("Não estou conectado a um canal de voz neste servidor.")
        await vc.disconnect(force=True)
        await ctx.reply("Saí do canal de voz.")

    @commands.Cog.listener()
    async def on_message(self,message: discord.Message):
        if not message.guild or message.author.bot: return
        cfg = await self.get_config(message.guild.id)
        if cfg.get("anti_links_enabled") and re.search(r"https?://|discord\.gg/", message.content, re.I):
            try:
                await message.delete()
                await self.audit(message.guild, message.author.id, "Link bloqueado pelo AutoMod", {"canal": getattr(message.channel, "name", "desconhecido"), "mensagem_id": message.id}, "log_internal_channel_id", GOLD)
            except discord.HTTPException: pass
            return
        if cfg.get("anti_spam_enabled"):
            now = asyncio.get_running_loop().time()
            bucket = self._message_windows[(message.guild.id, message.author.id)]
            bucket.append(now)
            while bucket and now - bucket[0] > 8: bucket.popleft()
            if len(bucket) >= 6:
                try:
                    await message.delete()
                    await self.audit(message.guild, message.author.id, "Spam bloqueado pelo AutoMod", {"canal": getattr(message.channel, "name", "desconhecido"), "mensagens_em_8s": len(bucket)}, "log_internal_channel_id", GOLD)
                except discord.HTTPException: pass
                bucket.clear()
                return
        if cfg.get("xp_enabled") and len(message.content.strip()) >= 3:
            await self.pool.execute("INSERT INTO sistemas_xp(guild_id,user_id,xp,level,last_message_at) VALUES($1,$2,5,0,NOW()) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=sistemas_xp.xp+5,level=FLOOR(SQRT((sistemas_xp.xp+5)/100.0))::INTEGER,last_message_at=NOW() WHERE sistemas_xp.last_message_at IS NULL OR sistemas_xp.last_message_at < NOW()-INTERVAL '60 seconds'", message.guild.id, message.author.id)
        removed=await self.pool.fetchrow("DELETE FROM sistemas_afk WHERE guild_id=$1 AND user_id=$2 RETURNING reason",message.guild.id,message.author.id)
        if removed:
            try: await message.channel.send(embed=embed("☀️ Bem-vindo de volta",f"{message.author.mention}, seu AFK foi removido."),delete_after=8)
            except discord.HTTPException: pass
        if message.mentions:
            rows=await self.pool.fetch("SELECT user_id,reason,since FROM sistemas_afk WHERE guild_id=$1 AND user_id=ANY($2::BIGINT[])",message.guild.id,[m.id for m in message.mentions])
            for r in rows:
                try: await message.channel.send(f"🌙 <@{r['user_id']}> está AFK: {r['reason'] or 'sem motivo informado'}.",delete_after=10)
                except discord.HTTPException: pass

    @app_commands.command(name="config_sala_temporaria", description="Configura o canal de entrada e categoria das salas temporárias.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_temp(self, inter: discord.Interaction, canal_entrada: discord.VoiceChannel, categoria: discord.CategoryChannel):
        await self.set_config(inter.guild.id,"temp_voice_trigger_id",canal_entrada.id)
        await self.set_config(inter.guild.id,"temp_voice_category_id",categoria.id)
        await respond(inter,"Sistema de salas temporárias configurado.")

    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        if before.channel and before.channel != after.channel and before.channel.id in {r["channel_id"] for r in await self.pool.fetch("SELECT channel_id FROM sistemas_temp_voice")}:
            if not before.channel.members:
                await self.pool.execute("DELETE FROM sistemas_temp_voice WHERE channel_id=$1",before.channel.id)
                try: await before.channel.delete(reason="Sala temporária vazia")
                except discord.HTTPException: pass
        if not after.channel or before.channel == after.channel: return
        cfg=await self.get_config(member.guild.id)
        if after.channel.id != cfg.get("temp_voice_trigger_id"): return
        lock=self._voice_locks.setdefault(member.guild.id,asyncio.Lock())
        async with lock:
            if not member.voice or member.voice.channel != after.channel: return
            category=member.guild.get_channel(cfg.get("temp_voice_category_id")) if cfg.get("temp_voice_category_id") else None
            try:
                channel=await member.guild.create_voice_channel(f"🔊・{member.display_name}",category=category,reason="Sala temporária")
                await channel.set_permissions(member,connect=True,manage_channels=True,move_members=True)
                await member.move_to(channel)
                await self.pool.execute("INSERT INTO sistemas_temp_voice(channel_id,guild_id,owner_id) VALUES($1,$2,$3)",channel.id,member.guild.id,member.id)
            except discord.HTTPException:
                log.exception("Falha ao criar sala temporária")

    @app_commands.command(name="criar_embed", description="Cria uma mensagem personalizada via webhook.")
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def webhook_embed(self, inter: discord.Interaction, canal: discord.TextChannel, titulo: str, descricao: str, cor_hex: str="#7048BE", imagem_url: Optional[str]=None):
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}",cor_hex): return await respond(inter,"Cor inválida. Use #7048BE.")
        if not valid_url(imagem_url): return await respond(inter,"URL de imagem inválida.")
        e=discord.Embed(title=titulo,description=descricao,colour=discord.Colour(int(cor_hex.lstrip("#"),16)))
        if imagem_url: e.set_image(url=imagem_url)
        try:
            hooks=await canal.webhooks()
            hook=next((h for h in hooks if h.user==self.bot.user and h.name=="Central Administrativa"),None)
            if hook is None: hook=await canal.create_webhook(name="Central Administrativa",reason=f"Solicitado por {inter.user}")
            await hook.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc: return await respond(inter,f"Falha no webhook: {clipped(exc,250)}")
        await respond(inter,f"Embed publicado em {canal.mention}.")

    @app_commands.command(name="config_automod", description="Ativa filtros básicos de spam e links para este servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_automod(self, inter: discord.Interaction, anti_spam: bool, anti_links: bool):
        await self.set_config(inter.guild.id, "anti_spam_enabled", anti_spam)
        await self.set_config(inter.guild.id, "anti_links_enabled", anti_links)
        await self.audit(inter.guild, inter.user.id, "AutoMod configurado", {"anti_spam": anti_spam, "anti_links": anti_links}, "log_internal_channel_id")
        await respond(inter, f"AutoMod atualizado. Anti-spam: **{'ativo' if anti_spam else 'inativo'}**. Filtro de links: **{'ativo' if anti_links else 'inativo'}**.")

    @app_commands.command(name="enquete", description="Publica uma enquete com até cinco opções.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def poll(self, inter: discord.Interaction, pergunta: str, opcoes: str, canal: Optional[discord.TextChannel] = None):
        choices = [x.strip() for x in re.split(r"[|;]", opcoes) if x.strip()]
        if not 2 <= len(choices) <= 5: return await respond(inter, "Informe de 2 a 5 opções separadas por |.")
        target = canal or inter.channel
        e = embed("📊 ENQUETE DA COMUNIDADE", pergunta)
        marks = ["🇦", "🇧", "🇨", "🇩", "🇪"]
        for mark, choice in zip(marks, choices): e.add_field(name=mark, value=choice, inline=False)
        e.add_field(name="Como participar", value="Reaja com o símbolo correspondente à sua opção. A enquete ficará aberta até a equipe encerrar.", inline=False)
        msg = await target.send(embed=e)
        for mark in marks[:len(choices)]: await msg.add_reaction(mark)
        await respond(inter, f"Enquete publicada em {target.mention}.")

    @app_commands.command(name="config_boas_vindas", description="Configura a mensagem de boas-vindas e o canal de entrada.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_welcome(self, inter: discord.Interaction, canal: discord.TextChannel, mensagem: str):
        if len(mensagem) > 1500: return await respond(inter, "A mensagem deve ter no máximo 1500 caracteres.")
        await self.set_config(inter.guild.id, "welcome_channel_id", canal.id)
        await self.set_config(inter.guild.id, "welcome_message", mensagem)
        await self.audit(inter.guild, inter.user.id, "Boas-vindas configuradas", {"canal_id": canal.id, "mensagem": mensagem}, "log_internal_channel_id")
        await respond(inter, f"Boas-vindas configuradas em {canal.mention}. Use {{member}} e {{server}} como variáveis.")

    @app_commands.command(name="config_autorole", description="Define o cargo automático de novos membros.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_autorole(self, inter: discord.Interaction, cargo: Optional[discord.Role]):
        await self.set_config(inter.guild.id, "autorole_id", cargo.id if cargo else None)
        await self.audit(inter.guild, inter.user.id, "Autorole configurado", {"cargo_id": cargo.id if cargo else "desativado"}, "log_internal_channel_id")
        await respond(inter, f"Cargo automático: {cargo.mention if cargo else 'desativado'}.")

    @app_commands.command(name="config_xp", description="Ativa ou desativa o sistema de experiência por mensagens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_xp(self, inter: discord.Interaction, ativo: bool):
        await self.set_config(inter.guild.id, "xp_enabled", ativo)
        await self.audit(inter.guild, inter.user.id, "Sistema de XP alterado", {"ativo": ativo}, "log_internal_channel_id")
        await respond(inter, f"Sistema de experiência {'ativado' if ativo else 'desativado'}.")

    @app_commands.command(name="ranking_xp", description="Exibe o ranking de experiência do servidor.")
    async def xp_ranking(self, inter: discord.Interaction):
        rows = await self.pool.fetch("SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10", inter.guild.id)
        e = embed("🏆 RANKING DE EXPERIÊNCIA", "Os membros mais ativos do servidor, de acordo com a experiência registrada.")
        if not rows: e.description += "\n\nAinda não há pontuação registrada. A administração pode ativar o sistema com /config_xp."
        else:
            for idx, r in enumerate(rows, 1): e.add_field(name=f"{idx}º lugar", value=f"<@{r['user_id']}> • **{r['xp']} XP**", inline=False)
        await respond(inter, em=e)

    @app_commands.command(name="painel_denuncias", description="Publica a central profissional de denúncias.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_panel(self, inter: discord.Interaction, canal: discord.TextChannel):
        e = embed("🛡️ CENTRAL DE DENÚNCIAS", "Este canal recebe relatos formais de ocorrências. Informe os fatos com clareza, identifique o membro envolvido e forneça links de evidências quando disponíveis. Cada envio recebe um protocolo e é encaminhado à equipe responsável.")
        cfg = await self.get_config(inter.guild.id)
        if cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
        await canal.send(embed=e, view=ReportPanel())
        await respond(inter, f"Central de denúncias publicada em {canal.mention}.")

    @app_commands.command(name="config_imagem_tema", description="Define a imagem temática usada nos painéis e logs.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_theme_image(self, inter: discord.Interaction, url: str):
        if not url.lower().startswith("https://") or not valid_url(url): return await respond(inter, "Informe uma URL HTTPS válida para a imagem.")
        await self.set_config(inter.guild.id, "theme_image_url", url)
        await self.audit(inter.guild, inter.user.id, "Imagem temática alterada", {"url": url}, "log_internal_channel_id")
        await respond(inter, "Imagem temática atualizada. Os próximos painéis e logs usarão essa imagem.")

    @app_commands.command(name="confiar_admin", description="Adiciona ou remove um administrador da lista confiável Anti-Nuke.")
    @app_commands.checks.has_permissions(administrator=True)
    async def trust_admin(self, inter: discord.Interaction, usuario_id: str, confiavel: bool):
        if not usuario_id.isdigit(): return await respond(inter, "Informe um ID numérico válido.")
        cfg = await self.get_config(inter.guild.id)
        ids = set(cfg.get("trusted_admin_ids") or [])
        if confiavel: ids.add(int(usuario_id))
        else: ids.discard(int(usuario_id))
        await self.set_config(inter.guild.id, "trusted_admin_ids", sorted(ids))
        await self.audit(inter.guild, inter.user.id, "Lista Anti-Nuke atualizada", {"usuario_id": usuario_id, "confiavel": confiavel}, "log_internal_channel_id")
        await respond(inter, f"ID `{usuario_id}` {'adicionado à' if confiavel else 'removido da'} lista confiável.")

    @app_commands.command(name="config_protecao", description="Ativa ou desativa alertas Anti-Raid e Anti-Nuke.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_protection(self, inter: discord.Interaction, anti_raid: bool, anti_nuke: bool):
        await self.set_config(inter.guild.id, "anti_raid_enabled", anti_raid)
        await self.set_config(inter.guild.id, "anti_nuke_enabled", anti_nuke)
        await self.audit(inter.guild, inter.user.id, "Proteções alteradas", {"anti_raid": anti_raid, "anti_nuke": anti_nuke}, "log_internal_channel_id", GOLD)
        await respond(inter, f"Proteções atualizadas. Anti-Raid: **{'ativo' if anti_raid else 'inativo'}**. Anti-Nuke: **{'ativo' if anti_nuke else 'inativo'}**. Nesta versão, as proteções geram alertas e não executam punições automáticas.")

    @app_commands.command(name="denunciar", description="Registra uma denúncia formal para análise da equipe.")
    async def report_command(self, inter: discord.Interaction, id_membro: str, relato: str, provas: Optional[str] = None):
        if not id_membro.isdigit(): return await respond(inter, "ID do membro inválido.")
        await self.create_report(inter, int(id_membro), relato, provas)

    @app_commands.command(name="sugerir", description="Envia uma sugestão para a equipe do servidor.")
    async def suggest(self, inter: discord.Interaction, sugestao: str):
        cfg = await self.get_config(inter.guild.id)
        channel = inter.guild.get_channel(cfg.get("suggestion_channel_id")) if cfg.get("suggestion_channel_id") else None
        if not channel: return await respond(inter, "O canal de sugestões ainda não foi configurado.")
        sid = await self.pool.fetchval("INSERT INTO sistemas_suggestions(guild_id,user_id,content) VALUES($1,$2,$3) RETURNING id", inter.guild.id, inter.user.id, sugestao)
        e = embed(f"💡 SUGESTÃO • #{sid}", "Uma nova proposta foi enviada para avaliação da comunidade e da equipe.")
        e.add_field(name="Autor", value=f"{inter.user.mention} (`{inter.user.id}`)", inline=False)
        e.add_field(name="Proposta", value=clipped(sugestao, 3000), inline=False)
        msg = await channel.send(embed=e)
        await msg.add_reaction("👍"); await msg.add_reaction("👎")
        await respond(inter, f"Sugestão enviada com protocolo **#{sid}**.")

    @app_commands.command(name="ficha_membro", description="Consulta ficha administrativa e histórico de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def member_file(self, inter: discord.Interaction, membro: discord.Member):
        rows = await self.pool.fetch("SELECT id,action,reason,moderator_id,created_at,active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 12", inter.guild.id, membro.id)
        active = sum(1 for r in rows if r["active"])
        e = embed(f"{EMOJI['id']} FICHA ADMINISTRATIVA • {membro}", "Visão consolidada dos registros administrativos deste membro.")
        e.set_thumbnail(url=membro.display_avatar.url)
        e.add_field(name="Identificação", value=f"{membro.mention}\n`{membro.id}`", inline=True)
        e.add_field(name="Conta criada", value=f"<t:{int(membro.created_at.timestamp())}:F>", inline=True)
        e.add_field(name="Entrou no servidor", value=f"<t:{int(membro.joined_at.timestamp())}:F>" if membro.joined_at else "Não disponível", inline=True)
        e.add_field(name="Registros encontrados", value=str(len(rows)), inline=True)
        e.add_field(name="Registros ativos", value=str(active), inline=True)
        e.add_field(name="Cargos", value=clipped(", ".join(r.mention for r in membro.roles[1:]) or "Nenhum", 900), inline=False)
        for r in rows[:8]: e.add_field(name=f"Caso #{r['id']} • {r['action']} • {'ativo' if r['active'] else 'inativo'}", value=clipped(f"{r['reason']}\nResponsável: <@{r['moderator_id']}> • <t:{int(r['created_at'].timestamp())}:R>", 800), inline=False)
        await respond(inter, em=e)

    @commands.command(name="denunciar")
    @commands.guild_only()
    async def prefix_report(self, ctx: commands.Context, id_membro: int, *, relato: str):
        class FakeInteraction: pass
        # Prefix path uses the same persistence and channel policy as the slash command.
        cfg = await self.get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(cfg.get("report_channel_id")) if cfg.get("report_channel_id") else None
        if not channel: return await ctx.reply("O canal de denúncias ainda não foi configurado.")
        rid = await self.pool.fetchval("INSERT INTO sistemas_reports(guild_id,reporter_id,target_id,reason) VALUES($1,$2,$3,$4) RETURNING id", ctx.guild.id, ctx.author.id, id_membro, relato)
        e = embed(f"🛡️ DENÚNCIA • PROTOCOLO #{rid}", "Uma denúncia foi registrada para análise da equipe.")
        e.add_field(name="Denunciante", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
        e.add_field(name="Membro denunciado", value=f"<@{id_membro}> (`{id_membro}`)", inline=False)
        e.add_field(name="Relato", value=clipped(relato, 3000), inline=False)
        await channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await ctx.reply(f"Denúncia registrada com protocolo **#{rid}**.")

    @commands.command(name="sugerir")
    @commands.guild_only()
    async def prefix_suggest(self, ctx: commands.Context, *, sugestao: str):
        cfg = await self.get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(cfg.get("suggestion_channel_id")) if cfg.get("suggestion_channel_id") else None
        if not channel: return await ctx.reply("O canal de sugestões ainda não foi configurado.")
        sid = await self.pool.fetchval("INSERT INTO sistemas_suggestions(guild_id,user_id,content) VALUES($1,$2,$3) RETURNING id", ctx.guild.id, ctx.author.id, sugestao)
        e = embed(f"💡 SUGESTÃO • #{sid}", "Uma nova proposta foi enviada para avaliação.")
        e.add_field(name="Autor", value=ctx.author.mention, inline=False); e.add_field(name="Proposta", value=clipped(sugestao, 3000), inline=False)
        msg = await channel.send(embed=e); await msg.add_reaction("👍"); await msg.add_reaction("👎")
        await ctx.reply(f"Sugestão enviada com protocolo **#{sid}**.")

    @commands.command(name="logs")
    @commands.guild_only()
    async def prefix_logs(self, ctx: commands.Context, limite: int = 10):
        cfg = await self.get_config(ctx.guild.id)
        if not is_staff(ctx.author, cfg): return await ctx.reply("Você não tem permissão para consultar a auditoria.")
        limite = max(1, min(limite, 20))
        rows = await self.pool.fetch("SELECT id,actor_id,action,details,created_at FROM sistemas_audit WHERE guild_id=$1 ORDER BY id DESC LIMIT $2", ctx.guild.id, limite)
        e = embed("📋 AUDITORIA ADMINISTRATIVA", f"Últimos {len(rows)} registros de alterações e atividades registradas pelo sistema.")
        for r in rows:
            details = r["details"] if isinstance(r["details"], dict) else json.loads(r["details"] or "{}")
            summary = " • ".join(f"{k}: {v}" for k,v in list(details.items())[:3])
            e.add_field(name=f"#{r['id']} • {r['action']}", value=clipped(f"Responsável: <@{r['actor_id']}>\n{summary}\n<t:{int(r['created_at'].timestamp())}:R>", 900), inline=False)
        await ctx.reply(embed=e)

    async def create_backup(self,guild_id: int):
        cfg=await self.get_config(guild_id)
        cases=await self.pool.fetch("SELECT * FROM sistemas_cases WHERE guild_id=$1 ORDER BY id",guild_id)
        requests=await self.pool.fetch("SELECT * FROM sistemas_requests WHERE guild_id=$1 ORDER BY id",guild_id)
        appeals=await self.pool.fetch("SELECT * FROM sistemas_appeals WHERE guild_id=$1 ORDER BY id",guild_id)
        def conv(row):
            return {k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in dict(row).items()}
        payload={"config":cfg,"cases":[conv(x) for x in cases],"requests":[conv(x) for x in requests],"appeals":[conv(x) for x in appeals]}
        await self.pool.execute("INSERT INTO sistemas_backups(guild_id,payload) VALUES($1,$2::jsonb)",guild_id,json.dumps(payload,default=str))

    @tasks.loop(hours=24)
    async def backup_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try: await self.create_backup(guild.id)
            except Exception: log.exception("Backup automático falhou para guild %s",guild.id)

    @backup_loop.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="backup_manual", description="Cria um backup manual dos dados administrativos.")
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_manual(self, inter: discord.Interaction):
        await self.create_backup(inter.guild.id)
        await respond(inter,"Backup criado com sucesso.")

    @app_commands.command(name="backup_listar", description="Lista os backups disponíveis.")
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_list(self, inter: discord.Interaction):
        rows=await self.pool.fetch("SELECT id,created_at FROM sistemas_backups WHERE guild_id=$1 ORDER BY id DESC LIMIT 10",inter.guild.id)
        e=embed("Backups disponíveis","\\n".join(f"#{r['id']} • {r['created_at']:%d/%m/%Y %H:%M UTC}" for r in rows) or "Nenhum backup encontrado.")
        await respond(inter,em=e)

    @app_commands.command(name="backup_restaurar", description="Restaura configurações de um backup (não desfaz punições no Discord).")
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_restore(self, inter: discord.Interaction, backup_id: int):
        row=await self.pool.fetchrow("SELECT payload FROM sistemas_backups WHERE id=$1 AND guild_id=$2",backup_id,inter.guild.id)
        if not row: return await respond(inter,"Backup não encontrado.")
        payload=row["payload"]
        if isinstance(payload, str):
            payload=json.loads(payload)
        await self.pool.execute("INSERT INTO sistemas_config(guild_id,data) VALUES($1,$2::jsonb) ON CONFLICT(guild_id) DO UPDATE SET data=EXCLUDED.data",inter.guild.id,json.dumps(payload["config"]))
        await respond(inter,"Configurações restauradas. Os registros históricos permanecem preservados; a restauração não reverte ações já executadas no Discord.")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if not ctx.guild: return
        # Registra nome e contexto, sem copiar o texto bruto para evitar exposição de dados sensíveis.
        await self.audit(ctx.guild, ctx.author.id, "Comando de prefixo executado", {"comando": ctx.command.qualified_name if ctx.command else "desconhecido", "canal": getattr(ctx.channel, "name", "DM"), "mensagem_id": ctx.message.id}, "log_internal_channel_id")

    @commands.Cog.listener()
    async def on_app_command_completion(self, inter: discord.Interaction, command: app_commands.Command):
        if not inter.guild: return
        await self.audit(inter.guild, inter.user.id, "Comando slash executado", {"comando": command.qualified_name, "canal_id": inter.channel_id, "interaction_id": inter.id}, "log_internal_channel_id")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        actor = await self.resolve_audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        await self.audit(role.guild, actor, "Cargo criado", {"cargo": role.name, "cargo_id": role.id}, "log_role_channel_id")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        cfg = await self.get_config(role.guild.id)
        actor_id = await self.resolve_audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        if cfg.get("anti_nuke_enabled"):
            trusted = set(cfg.get("trusted_admin_ids") or [])
            if actor_id and actor_id not in trusted and actor_id != self.bot.user.id:
                await self.send_log(role.guild, "log_internal_channel_id", "🚨 ALERTA ANTI-NUKE • EXCLUSÃO DE CARGO", f"Um cargo foi excluído por <@{actor_id}>. Cargo: **{role.name}** (`{role.id}`). Verifique imediatamente o registro de auditoria do Discord.", RED)
        await self.audit(role.guild, actor_id, "Cargo excluído", {"cargo": role.name, "cargo_id": role.id}, "log_role_channel_id", RED)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = {}
        for attr in ("name", "colour", "hoist", "mentionable", "permissions", "position"):
            old, new = getattr(before, attr, None), getattr(after, attr, None)
            if old != new: changes[attr] = f"{old} → {new}"
        if changes:
            actor = await self.resolve_audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
            await self.audit(after.guild, actor, "Cargo alterado", {"cargo": after.name, **changes}, "log_role_channel_id")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = {}
        for attr in ("name", "topic", "slowmode_delay", "nsfw", "bitrate", "user_limit", "category_id"):
            old, new = getattr(before, attr, None), getattr(after, attr, None)
            if old != new: changes[attr] = f"{old} → {new}"
        before_ow = {getattr(t, "id", 0): str(o) for t,o in before.overwrites.items()}
        after_ow = {getattr(t, "id", 0): str(o) for t,o in after.overwrites.items()}
        if before_ow != after_ow: changes["permissões_overwrite"] = f"{before_ow} → {after_ow}"
        if changes:
            actor = await self.resolve_audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
            await self.audit(after.guild, actor, "Canal alterado", {"canal": after.name, **changes}, "log_server_channel_id")

    @commands.Cog.listener()
    async def on_guild_channel_create(self,channel):
        cfg = await self.get_config(channel.guild.id)
        quarantine = channel.guild.get_role(cfg.get("quarantine_role_id")) if cfg.get("quarantine_role_id") else None
        if quarantine:
            try: await channel.set_permissions(quarantine, view_channel=False, send_messages=False, connect=False, reason="Aplicar restrição de quarentena em canal novo")
            except discord.HTTPException: log.exception("Falha ao aplicar overwrite de quarentena no canal novo")
        actor = await self.resolve_audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        await self.audit(channel.guild, actor, "Canal criado", {"canal": channel.name, "canal_id": channel.id}, "log_server_channel_id")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel):
        cfg = await self.get_config(channel.guild.id)
        actor_id = await self.resolve_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if cfg.get("anti_nuke_enabled"):
            trusted = set(cfg.get("trusted_admin_ids") or [])
            if actor_id and actor_id not in trusted and actor_id != self.bot.user.id:
                await self.send_log(channel.guild, "log_internal_channel_id", "🚨 ALERTA ANTI-NUKE • EXCLUSÃO DE CANAL", f"Um canal foi excluído por <@{actor_id}>. Canal: **{channel.name}** (`{channel.id}`). Verifique imediatamente o registro de auditoria do Discord.", RED)
        await self.audit(channel.guild, actor_id, "Canal excluído", {"canal": channel.name, "canal_id": channel.id}, "log_server_channel_id", RED)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = {}
        for attr in ("name", "description", "verification_level", "explicit_content_filter", "afk_timeout", "default_notifications"):
            old, new = getattr(before, attr, None), getattr(after, attr, None)
            if old != new: changes[attr] = f"{old} → {new}"
        if changes:
            actor = await self.resolve_audit_actor(after, discord.AuditLogAction.guild_update, after.id)
            await self.audit(after, actor, "Configurações do servidor alteradas", changes, "log_server_channel_id")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        actor = await self.resolve_audit_actor(guild, discord.AuditLogAction.ban, user.id)
        await self.audit(guild, actor, "Membro banido", {"membro": str(user), "membro_id": user.id}, "log_punishment_channel_id", RED)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        actor = await self.resolve_audit_actor(guild, discord.AuditLogAction.unban, user.id)
        await self.audit(guild, actor, "Membro desbanido", {"membro": str(user), "membro_id": user.id}, "log_punishment_channel_id", GREEN)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild and not message.author.bot:
            await self.audit(message.guild, None, "Mensagem excluída", {"autor": str(message.author), "autor_id": message.author.id, "canal": getattr(message.channel, "name", "desconhecido"), "conteudo": clipped(message.content or "sem conteúdo em cache", 500)}, "log_server_channel_id", GOLD)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild and not before.author.bot and before.content != after.content:
            await self.audit(before.guild, before.author.id, "Mensagem editada", {"canal": getattr(before.channel, "name", "desconhecido"), "antes": clipped(before.content or "vazio", 450), "depois": clipped(after.content or "vazio", 450)}, "log_server_channel_id")

    @commands.Cog.listener()
    async def on_member_join(self,member):
        cfg = await self.get_config(member.guild.id)
        if cfg.get("anti_raid_enabled"):
            now = asyncio.get_running_loop().time()
            window = self._join_windows[member.guild.id]
            window.append(now)
            while window and now - window[0] > int(cfg.get("anti_raid_window_seconds") or 12): window.popleft()
            threshold = int(cfg.get("anti_raid_threshold") or 6)
            if len(window) >= threshold:
                await self.send_log(member.guild, "log_internal_channel_id", "🚨 ALERTA ANTI-RAID", f"Foram detectadas **{len(window)} entradas** em {cfg.get('anti_raid_window_seconds',12)} segundos. Última entrada: {member.mention}. A proteção está em modo de alerta; nenhuma ação automática foi executada.", RED)
                window.clear()
        await self.send_log(member.guild,"log_member_channel_id","Membro entrou",f"{member.mention} (`{member.id}`)")
        welcome_channel = member.guild.get_channel(cfg.get("welcome_channel_id")) if cfg.get("welcome_channel_id") else None
        if welcome_channel:
            message = str(cfg.get("welcome_message") or "Bem-vindo(a), {member}, ao servidor {server}!")
            message = message.replace("{member}", member.mention).replace("{server}", member.guild.name)
            e = embed("✦ BOAS-VINDAS", message)
            e.set_thumbnail(url=member.display_avatar.url)
            if cfg.get("theme_image_url"): e.set_image(url=cfg["theme_image_url"])
            await welcome_channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        autorole = member.guild.get_role(cfg.get("autorole_id")) if cfg.get("autorole_id") else None
        if autorole:
            try: await member.add_roles(autorole, reason="Cargo automático de entrada")
            except discord.HTTPException: log.exception("Falha ao atribuir autorole")
        cfg=await self.get_config(member.guild.id)
        if any(r.id in set(cfg.get("staff_role_ids") or []) for r in member.roles):
            await self.pool.execute("INSERT INTO sistemas_staff(guild_id,user_id,active) VALUES($1,$2,TRUE) ON CONFLICT(guild_id,user_id) DO UPDATE SET active=TRUE,last_seen=NOW()",member.guild.id,member.id)

    @commands.Cog.listener()
    async def on_member_remove(self,member):
        await self.send_log(member.guild,"log_member_channel_id","Membro saiu",f"**{member}** (`{member.id}`)",RED)
        await self.pool.execute("UPDATE sistemas_staff SET active=FALSE,last_seen=NOW() WHERE guild_id=$1 AND user_id=$2",member.guild.id,member.id)

    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        a={r.id for r in before.roles}; b={r.id for r in after.roles}
        if a != b:
            actor = await self.resolve_audit_actor(after.guild, discord.AuditLogAction.member_role_update, after.id)
            await self.audit(after.guild, actor, "Cargos de membro alterados", {"membro": after.mention, "adicionados": ', '.join(f'<@&{x}>' for x in b-a) or '—', "removidos": ', '.join(f'<@&{x}>' for x in a-b) or '—'}, "log_role_channel_id")

    @commands.Cog.listener()
    async def on_app_command_error(self,inter,error):
        log.exception("Erro em comando de aplicação",exc_info=error)
        try: await respond(inter,"Ocorreu um erro ao executar essa ação. A equipe foi notificada.")
        except Exception: pass
        if inter.guild:
            await self.send_log(inter.guild,"log_internal_channel_id","Erro interno do bot",clipped(error,900),RED)

async def setup(bot: commands.Bot):
    main_module=sys.modules.get("__main__")
    pool=getattr(main_module,"db_pool",None) if main_module else None
    if pool is None:
        # Também aceita importação convencional do módulo principal.
        main_module=sys.modules.get("main")
        pool=getattr(main_module,"db_pool",None) if main_module else None
    if pool is None or not hasattr(pool,"acquire"):
        raise RuntimeError("db_pool não encontrado. Crie a conexão Supabase antes de carregar sistemas.py.")
    # Acrescenta o prefixo solicitado sem remover o prefixo antigo do main.py,
    # preservando comandos legados (inclusive os do sistema de tickets).
    current = getattr(bot, "command_prefix", "!")
    if isinstance(current, str):
        prefixes = [".", current] if current != "." else ["."]
        bot.command_prefix = commands.when_mentioned_or(*prefixes)
    elif isinstance(current, (tuple, list)):
        bot.command_prefix = commands.when_mentioned_or(".", *current)
    elif callable(current):
        async def combined_prefix(bot_instance, message):
            existing = current(bot_instance, message)
            if inspect.isawaitable(existing): existing = await existing
            values = [existing] if isinstance(existing, str) else list(existing or [])
            return list(dict.fromkeys([".", *values]))
        bot.command_prefix = combined_prefix
    await bot.add_cog(Systems(bot,pool))
