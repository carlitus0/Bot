# -*- coding: utf-8 -*-
"""
Extensão de sistemas administrativos para discord.py 2.x / Python 3.11+.
Integração: main.py deve criar `db_pool` (asyncpg.Pool) antes de carregar esta extensão.
"""
from __future__ import annotations

import asyncio
import json
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
}

def embed(title: str, description: str = "", color: discord.Colour = PURPLE) -> discord.Embed:
    e = discord.Embed(title=title, description=description, colour=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text="Central Administrativa • Sistema de Moderação")
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
    punishment = discord.ui.TextInput(label="Punição solicitada", placeholder="warn, mute, kick, ban ou quarentena", max_length=20)
    reason = discord.ui.TextInput(label="Motivo detalhado", style=discord.TextStyle.paragraph, min_length=5, max_length=1500)
    occurred = discord.ui.TextInput(label="Data do ocorrido", placeholder="DD/MM/AAAA ou data aproximada", max_length=50)
    witnesses = discord.ui.TextInput(label="Testemunhas (opcional)", required=False, max_length=500)

    async def on_submit(self, inter: discord.Interaction):
        cog = inter.client.get_cog("Systems")
        if not cog:
            return await respond(inter, "Sistema indisponível.")
        if not self.accused_id.value.isdigit():
            return await respond(inter, "O ID precisa conter apenas números.")
        kind = self.punishment.value.lower().strip()
        aliases = {"advertencia":"warn", "advertência":"warn", "banimento":"ban", "expulsao":"kick", "expulsão":"kick", "mute":"mute", "quarentena":"quarentena"}
        kind = aliases.get(kind, kind)
        if kind not in {"warn", "mute", "kick", "ban", "quarentena"}:
            return await respond(inter, "Punição inválida. Use warn, mute, kick, ban ou quarentena.")
        await cog.create_request(inter, int(self.accused_id.value), kind, self.reason.value.strip(), self.occurred.value.strip(), self.witnesses.value.strip() or None, None)

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
    def __init__(self, request_id: int):
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
        match = re.search(r"Solicitação #([0-9]+)", title)
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

class Systems(commands.Cog):
    def __init__(self, bot: commands.Bot, pool: asyncpg.Pool):
        self.bot, self.pool = bot, pool
        self._voice_locks: dict[int, asyncio.Lock] = {}
        self.backup_loop.start()

    async def cog_load(self):
        await self.create_schema()
        self.bot.add_view(PunishmentPanel())
        rows = await self.pool.fetch("SELECT id, review_message_id FROM sistemas_requests WHERE status='pending' AND review_message_id IS NOT NULL")
        for row in rows:
            self.bot.add_view(DecisionView(), message_id=row["review_message_id"])

    def cog_unload(self):
        self.backup_loop.cancel()

    async def create_schema(self):
        queries = [
        """CREATE TABLE IF NOT EXISTS sistemas_config(guild_id BIGINT PRIMARY KEY, data JSONB NOT NULL DEFAULT '{}'::jsonb, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_cases(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),active BOOLEAN NOT NULL DEFAULT TRUE)""",
        """CREATE TABLE IF NOT EXISTS sistemas_requests(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,requester_id BIGINT NOT NULL,target_id BIGINT NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,occurred TEXT,witnesses TEXT,evidence_url TEXT,evidence_attachment_url TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,decision_reason TEXT,review_message_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS sistemas_appeals(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,case_id BIGINT NOT NULL,appellant_id BIGINT NOT NULL,explanation TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS sistemas_afk(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,reason TEXT,since TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))""",
        """CREATE TABLE IF NOT EXISTS sistemas_staff(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))""",
        """CREATE TABLE IF NOT EXISTS sistemas_temp_voice(channel_id BIGINT PRIMARY KEY,guild_id BIGINT NOT NULL,owner_id BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sistemas_backups(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
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

    async def send_log(self, guild: discord.Guild, key: str, title: str, description: str, color=PURPLE):
        try:
            cfg = await self.get_config(guild.id)
            channel_id = cfg.get(key)
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel:
                await channel.send(embed=embed(title, description, color), allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            log.exception("Falha ao enviar log %s", key)

    async def notify_dm(self, user: discord.abc.User, guild: discord.Guild, action: str, reason: str, case_id: int, expires=None):
        titles = {"ban":"⛔ Você foi banido","kick":"👢 Você foi expulso","mute":"🔇 Você recebeu um mute","quarentena":"🔒 Você foi colocado em quarentena","warn":"⚠️ Você recebeu uma advertência","hackban":"⛔ Seu ID foi banido"}
        e = embed(titles.get(action, "Aviso de moderação"), f"Você recebeu uma medida administrativa em **{guild.name}**.", RED if action in {"ban","kick","hackban"} else PURPLE)
        e.add_field(name="Punição", value=action.upper(), inline=True)
        e.add_field(name="Registro", value=f"#{case_id}", inline=True)
        e.add_field(name="Motivo", value=clipped(reason, 900), inline=False)
        if expires:
            e.add_field(name="Duração", value=f"Até <t:{int(expires.timestamp())}:F>", inline=False)
        e.add_field(name="Revisão", value="Use o painel de revisão do servidor ou contate a equipe responsável. A punição não é removida automaticamente ao recorrer.", inline=False)
        try:
            await user.send(embed=e)
        except (discord.Forbidden, discord.HTTPException):
            await self.send_log(guild, "log_internal_channel_id", "DM não entregue", f"Não foi possível enviar DM para `{user.id}` sobre o caso `#{case_id}`.", GOLD)

    async def add_case(self, guild: discord.Guild, user_id: int, moderator_id: int, action: str, reason: str, expires=None) -> int:
        case_id = await self.pool.fetchval("""INSERT INTO sistemas_cases(guild_id,user_id,moderator_id,action,reason,expires_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id""", guild.id,user_id,moderator_id,action,reason,expires)
        await self.send_log(guild, "log_punishment_channel_id", f"Registro de punição • {action}", f"Caso `#{case_id}`\nMembro: <@{user_id}> (`{user_id}`)\nResponsável: <@{moderator_id}>\nMotivo: {reason}")
        return case_id

    async def create_request(self, inter, target_id: int, kind: str, reason: str, occurred: str, witnesses: Optional[str], attachment: Optional[discord.Attachment]):
        cfg = await self.get_config(inter.guild.id)
        member = inter.guild.get_member(target_id)
        user = member or await self.bot.fetch_user(target_id)
        attachment_url = attachment.url if attachment else None
        request_id = await self.pool.fetchval("""INSERT INTO sistemas_requests(guild_id,requester_id,target_id,kind,reason,occurred,witnesses,evidence_attachment_url) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""", inter.guild.id,inter.user.id,target_id,kind,reason,occurred,witnesses,attachment_url)
        channel_id = cfg.get("request_channel_id")
        channel = inter.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return await respond(inter, "Solicitação salva, mas o canal de solicitações ainda não foi configurado. Peça à administração para definir `/config_canal`.")
        e = embed(f"⚖️ Solicitação #{request_id}", "Uma nova solicitação aguarda análise.")
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
            msg = await channel.send(embed=e, view=DecisionView(), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return await respond(inter, "Não consegui publicar a solicitação. Confira as permissões do bot no canal.")
        await self.pool.execute("UPDATE sistemas_requests SET review_message_id=$1 WHERE id=$2", msg.id, request_id)
        self.bot.add_view(DecisionView(), message_id=msg.id)
        await self.send_log(inter.guild, "log_internal_channel_id", "Solicitação criada", f"Solicitação `#{request_id}` criada por {inter.user.mention}.")
        await respond(inter, f"Sua solicitação **#{request_id}** foi encaminhada para análise.")

    async def decide_request(self, inter: discord.Interaction, request_id: int, decision: str):
        row = await self.pool.fetchrow("SELECT * FROM sistemas_requests WHERE id=$1 AND guild_id=$2", request_id, inter.guild.id)
        if not row:
            return await respond(inter, "Solicitação não encontrada.")
        if row["status"] != "pending":
            return await respond(inter, "Essa solicitação já foi analisada.")
        if decision == "denied":
            await self.pool.execute("UPDATE sistemas_requests SET status='denied',reviewer_id=$1,decided_at=NOW(),decision_reason='Negada pela equipe' WHERE id=$2", inter.user.id, request_id)
            cfg=await self.get_config(inter.guild.id); ch=inter.guild.get_channel(cfg.get("denied_channel_id")) if cfg.get("denied_channel_id") else None
            if ch: await ch.send(embed=embed(f"❌ Solicitação #{request_id} negada", f"Acusado: <@{row['target_id']}>\nSolicitante: <@{row['requester_id']}>\nAnalisada por: {inter.user.mention}", RED))
            await inter.response.edit_message(embed=embed(f"Solicitação #{request_id} • NEGADA", "A solicitação foi recusada." ,RED), view=None)
            return
        if decision == "manual":
            await respond(inter, f"Solicitação #{request_id}: use o comando `/punir` para aplicar manualmente; a solicitação permanece pendente.")
            return
        kind = row["kind"]
        try:
            await self.apply_punishment(inter.guild, row["target_id"], inter.user, kind, row["reason"], None)
        except Exception as exc:
            return await respond(inter, f"Não foi possível aplicar automaticamente: {clipped(exc,250)}. A solicitação continua pendente para ação manual.")
        await self.pool.execute("UPDATE sistemas_requests SET status='approved',reviewer_id=$1,decided_at=NOW() WHERE id=$2", inter.user.id, request_id)
        cfg=await self.get_config(inter.guild.id); ch=inter.guild.get_channel(cfg.get("approved_channel_id")) if cfg.get("approved_channel_id") else None
        if ch: await ch.send(embed=embed(f"✅ Solicitação #{request_id} aprovada", f"Punição: **{kind}**\nAcusado: <@{row['target_id']}>\nAnalisada por: {inter.user.mention}", GREEN))
        await inter.response.edit_message(embed=embed(f"Solicitação #{request_id} • APROVADA", "Punição aplicada e registrada.", GREEN), view=None)

    async def apply_punishment(self, guild: discord.Guild, target_id: int, moderator: discord.Member, kind: str, reason: str, duration_minutes: Optional[int]):
        member = guild.get_member(target_id)
        bot_member = guild.me
        expires = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes) if duration_minutes else None
        if kind == "hackban":
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
            roles=[r for r in member.roles if r != guild.default_role]
            await member.remove_roles(*roles, reason="Aplicação de quarentena")
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
        appeal_id=await self.pool.fetchval("INSERT INTO sistemas_appeals(guild_id,case_id,appellant_id,explanation,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id",inter.guild.id,case_id,inter.user.id,explanation,evidence)
        cfg=await self.get_config(inter.guild.id); channel=inter.guild.get_channel(cfg.get("appeal_channel_id")) if cfg.get("appeal_channel_id") else None
        if not channel: return await respond(inter,"Recurso registrado, mas o canal de revisão ainda não foi configurado.")
        e=embed(f"📨 Recurso #{appeal_id}",f"Recurso referente à punição `#{case_id}`.")
        e.add_field(name="Membro",value=f"{inter.user} (`{inter.user.id}`)",inline=False)
        e.add_field(name="Justificativa",value=clipped(explanation),inline=False)
        e.add_field(name="Provas",value=evidence or "Não informadas",inline=False)
        await channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
        await respond(inter,f"Recurso **#{appeal_id}** enviado para análise. A punição continua ativa enquanto não houver decisão.")

    @app_commands.command(name="solicitar_punicao", description="Envia uma solicitação com prova em anexo opcional.")
    async def request_with_attachment(self, inter: discord.Interaction, id_acusado: str, tipo: str, motivo: str, data_ocorrido: str, testemunhas: Optional[str]=None, prova: Optional[discord.Attachment]=None):
        cfg=await self.get_config(inter.guild.id)
        if not isinstance(inter.user, discord.Member) or not is_staff(inter.user,cfg):
            return await respond(inter,"Você não tem autorização para solicitar punições.")
        if not id_acusado.isdigit():
            return await respond(inter,"ID do acusado inválido.")
        kind=tipo.lower()
        if kind not in {"warn","mute","kick","ban","quarentena"}:
            return await respond(inter,"Tipo inválido. Use warn, mute, kick, ban ou quarentena.")
        await self.create_request(inter,int(id_acusado),kind,motivo,data_ocorrido,testemunhas,prova)

    @app_commands.command(name="painel_punicoes", description="Publica o painel de solicitações de punição.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, inter: discord.Interaction, canal: discord.TextChannel):
        e=embed("⚖️ Central de solicitações","Utilize os botões abaixo para solicitar uma medida disciplinar ou recorrer de uma punição.\\n\\nA equipe analisará cada solicitação.")
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
    ])
    async def config_channel(self, inter: discord.Interaction, tipo: app_commands.Choice[str], canal: discord.TextChannel):
        await self.set_config(inter.guild.id,tipo.value,canal.id)
        await respond(inter,f"Canal **{tipo.name}** definido para {canal.mention}.")

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
    @app_commands.checks.has_permissions(moderate_members=True)
    async def punish(self, inter: discord.Interaction, tipo: str, id_membro: str, motivo: str, duracao_minutos: Optional[app_commands.Range[int,1,40320]]=None):
        if not id_membro.isdigit(): return await respond(inter,"ID inválido.")
        kind=tipo.lower()
        if kind not in {"warn","mute","kick","ban","quarentena","hackban"}: return await respond(inter,"Tipo inválido.")
        try:
            case=await self.apply_punishment(inter.guild,int(id_membro),inter.user,kind,motivo,duracao_minutos)
        except (discord.Forbidden,discord.NotFound,discord.HTTPException,ValueError) as exc:
            return await respond(inter,f"Não foi possível aplicar: {clipped(exc,300)}")
        await respond(inter,f"Punição **{kind}** aplicada. Registro `#{case}`.")

    @app_commands.command(name="clear_warn", description="Desativa advertências ativas de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def clear_warn(self, inter: discord.Interaction, membro: discord.Member, motivo: str):
        result=await self.pool.execute("UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND user_id=$2 AND action='warn' AND active=TRUE",inter.guild.id,membro.id)
        case=await self.add_case(inter.guild,membro.id,inter.user.id,"clear_warn",motivo)
        await respond(inter,f"Advertências ativas removidas. {result}. Registro `#{case}`.")

    @app_commands.command(name="historico_punicoes", description="Consulta o histórico de punições de um membro.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, inter: discord.Interaction, membro: discord.Member):
        rows=await self.pool.fetch("SELECT id,action,reason,moderator_id,created_at,active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15",inter.guild.id,membro.id)
        e=embed(f"Histórico • {membro}",f"Registros encontrados: {len(rows)}")
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['action']} • {'ativo' if r['active'] else 'inativo'}",value=clipped(f"{r['reason']}\\nResponsável: <@{r['moderator_id']}> • {r['created_at']:%d/%m/%Y %H:%M UTC}"),inline=False)
        await respond(inter,em=e)

    @app_commands.command(name="afk", description="Define seu status de ausência.")
    async def afk(self, inter: discord.Interaction, motivo: Optional[str]="Ausente"):
        await self.pool.execute("INSERT INTO sistemas_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()",inter.guild.id,inter.user.id,motivo)
        await respond(inter,"Seu status AFK foi ativado.")

    @commands.Cog.listener()
    async def on_message(self,message: discord.Message):
        if not message.guild or message.author.bot: return
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
    async def on_member_join(self,member):
        await self.send_log(member.guild,"log_member_channel_id","Membro entrou",f"{member.mention} (`{member.id}`)")
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
            await self.send_log(after.guild,"log_role_channel_id","Cargos alterados",f"{after.mention}\nAdicionados: {', '.join(f'<@&{x}>' for x in b-a) or '—'}\nRemovidos: {', '.join(f'<@&{x}>' for x in a-b) or '—'}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self,channel):
        await self.send_log(channel.guild,"log_server_channel_id","Canal criado",f"{channel.name} (`{channel.id}`)")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel):
        await self.send_log(channel.guild,"log_server_channel_id","Canal excluído",f"{channel.name} (`{channel.id}`)",RED)

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
    await bot.add_cog(Systems(bot,pool))
