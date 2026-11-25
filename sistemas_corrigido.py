"""Nexus Discord server systems consolidated into a single extension file.
Python 3.13 / discord.py 2.x / asyncpg. Load after main.py initializes db_pool.
The original main.py tickets and transcripts remain untouched.
"""
from __future__ import annotations
import asyncio, json, logging, os, re, sys, time, traceback
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
log = logging.getLogger('nexus')
PURPLE = discord.Colour(8141549)
BLUE = discord.Colour(2450411)
RED = discord.Colour(14427686)
GREEN = discord.Colour(1483594)
GOLD = discord.Colour(14251782)
BLACK = discord.Colour(1118232)
VISUALS = {'shield': 'https://files.catbox.moe/gsbbt1.png', 'banner': 'https://files.catbox.moe/9nlwvg.png', 'reference': 'https://files.catbox.moe/8w3qcf.jpg'}
EMOJI = {'alert': '<:emoji_33:1575019806636245012>', 'github': '<:emoji_34:1575019961322053832>', 'crown': '<:emoji_13:1556437078248656986>', 'tools': '<:emoji_19:1556439034891599952>', 'shield': '<:emoji_3:1556432452115898458>', 'search': '<:emoji_30:157501938723534858>', 'voice': '<:emoji_32:1575019682598092810>', 'members': '<:emoji_17:1556438860798501016>', 'ban': '<:emoji_10:1556436879086452766>', 'web': '<:emoji_12:1556437008778534942>', 'timer': '<:emoji_18:1556438970500522024>', 'calendar': '<:emoji_20:1556439152625713264>', 'id': '<:emoji_22:1556439311984103424>', 'bell': '<:emoji_6:1556436410037305386>', 'pin': '<:emoji_17:1556438912308617256>'}
DEFAULTS = {'trusted_admin_ids': [], 'staff_role_ids': [], 'reviewer_role_id': None, 'quarantine_role_id': None, 'quarantine_channel_id': None, 'request_channel_id': None, 'appeal_channel_id': None, 'approved_channel_id': None, 'denied_channel_id': None, 'report_channel_id': None, 'suggestion_channel_id': None, 'welcome_channel_id': None, 'recruitment_channel_id': None, 'welcome_message': 'Bem-vindo(a), {member}, ao {server}!', 'autorole_id': None, 'temp_voice_trigger_id': None, 'temp_voice_category_id': None, 'log_server_channel_id': None, 'log_member_channel_id': None, 'log_role_channel_id': None, 'log_punishment_channel_id': None, 'log_internal_channel_id': None, 'anti_raid_enabled': False, 'anti_raid_threshold': 6, 'anti_raid_window_seconds': 12, 'anti_nuke_enabled': False, 'anti_nuke_threshold': 4, 'anti_spam_enabled': False, 'anti_links_enabled': False, 'anti_invites_enabled': False, 'filter_words': [], 'max_mentions': 5, 'spam_count': 5, 'spam_window': 8, 'request_auto_types': [], 'xp_enabled': False, 'xp_cooldown': 60, 'theme_image_url': VISUALS['banner'], 'backup_interval_hours': 24, 'economy_daily': 100, 'economy_work_min': 25, 'economy_work_max': 100, 'economy_cooldown': 3600, 'remote_admin_ids': [], 'remote_enabled': False, 'remote_log_channel_id': None, 'shop_currency': 'BRL', 'payment_provider': 'disabled', 'payment_webhook_secret': None, 'payment_api_key': None, 'birthday_channel_id': None, 'starboard_channel_id': None, 'starboard_threshold': 3, 'starboard_emoji': '⭐', 'xp_level_message': '✨ {member} alcançou o nível {level}!', 'language': 'pt-br', 'timezone': 'UTC', 'economy_transfer_limit': 100000, 'verification_role_id': None, 'automod_bypass_role_ids': []}

def embed(title, description='', color=PURPLE):
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text='NEXUS • Administração & Comunidade')
    return e

def clip(v, n=1000):
    s = str(v)
    return s if len(s) <= n else s[:n - 1] + '…'

def url_ok(u):
    return not u or bool(re.match('^https?://', str(u), re.I))

async def reply(inter, content=None, em=None):
    if inter.response.is_done():
        await inter.followup.send(content=content, embed=em, ephemeral=True)
    else:
        await inter.response.send_message(content=content, embed=em, ephemeral=True)

def staff(member, cfg):
    if not isinstance(member, discord.Member):
        return False
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild or any((r.id in set(cfg.get('staff_role_ids') or []) | ({cfg['reviewer_role_id']} if cfg.get('reviewer_role_id') else set()) for r in member.roles))

def hierarchy(actor, target, botmember):
    if actor.id == target.id:
        return (False, 'Você não pode agir contra si mesmo.')
    if target.id == actor.guild.owner_id:
        return (False, 'O proprietário não pode ser alvo dessa ação.')
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return (False, 'O alvo possui cargo igual ou superior ao seu.')
    if target.top_role >= botmember.top_role:
        return (False, 'O cargo do alvo está acima ou igual ao cargo do bot.')
    return (True, '')

class Systems(commands.Cog):

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.started = time.monotonic()
        self.join_windows = defaultdict(deque)
        self.msg_windows = defaultdict(deque)
        self.voice_locks = defaultdict(asyncio.Lock)
        self.quarantine_task = self.expiry_loop
        self.expiry_loop.start()
        self.backup_loop.start()

    async def cog_load(self):
        await self.schema()
        self.bot.add_view(NexusPublicPanel())
        self.bot.add_view(NexusRemotePanel())
        for row in await self.pool.fetch("SELECT id,review_message_id FROM sistemas_requests WHERE status='pending' AND review_message_id IS NOT NULL"):
            self.bot.add_view(RequestDecisionView(int(row['id'])), message_id=row['review_message_id'])
        for row in await self.pool.fetch("SELECT id,review_message_id FROM sistemas_appeals WHERE status='pending' AND review_message_id IS NOT NULL"):
            self.bot.add_view(AppealDecisionView(int(row['id'])), message_id=row['review_message_id'])

    def cog_unload(self):
        self.expiry_loop.cancel()
        self.backup_loop.cancel()

    async def schema(self):
        ddl = ["CREATE TABLE IF NOT EXISTS sistemas_config(guild_id BIGINT PRIMARY KEY,data JSONB NOT NULL DEFAULT '{}'::jsonb,updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())", 'CREATE TABLE IF NOT EXISTS sistemas_cases(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),active BOOLEAN NOT NULL DEFAULT TRUE)', "CREATE TABLE IF NOT EXISTS sistemas_requests(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,requester_id BIGINT NOT NULL,target_id BIGINT NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,occurred TEXT,witnesses TEXT,evidence_url TEXT,evidence_attachment_url TEXT,duration_minutes INTEGER,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,decision_reason TEXT,review_message_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)", "CREATE TABLE IF NOT EXISTS sistemas_appeals(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,case_id BIGINT NOT NULL,appellant_id BIGINT NOT NULL,explanation TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,review_message_id BIGINT,decision_reason TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)", 'CREATE TABLE IF NOT EXISTS sistemas_afk(guild_id BIGINT NOT NULL,user_id BIGINT,reason TEXT,since TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS sistemas_staff(guild_id BIGINT NOT NULL,user_id BIGINT,active BOOLEAN NOT NULL DEFAULT TRUE,last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),role_name TEXT,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS sistemas_temp_voice(channel_id BIGINT PRIMARY KEY,guild_id BIGINT NOT NULL,owner_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS sistemas_backups(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())', "CREATE TABLE IF NOT EXISTS sistemas_audit(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,actor_id BIGINT,action TEXT NOT NULL,details JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())", "CREATE TABLE IF NOT EXISTS sistemas_reports(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,reporter_id BIGINT NOT NULL,target_id BIGINT NOT NULL,reason TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())", "CREATE TABLE IF NOT EXISTS sistemas_suggestions(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),message_id BIGINT)", 'CREATE TABLE IF NOT EXISTS sistemas_xp(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,xp BIGINT NOT NULL DEFAULT 0,level INTEGER NOT NULL DEFAULT 0,last_message_at TIMESTAMPTZ,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_wallets(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,balance BIGINT NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_economy_tx(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,from_user BIGINT,to_user BIGINT,amount BIGINT NOT NULL,kind TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())', "CREATE TABLE IF NOT EXISTS nexus_products(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,name TEXT NOT NULL,description TEXT DEFAULT '',price_cents BIGINT NOT NULL,stock INTEGER NOT NULL DEFAULT 0,active BOOLEAN NOT NULL DEFAULT TRUE,category TEXT,created_at TIMESTAMPTZ DEFAULT NOW())", "CREATE TABLE IF NOT EXISTS nexus_orders(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,product_id BIGINT NOT NULL,qty INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',total_cents BIGINT NOT NULL,payment_ref TEXT,created_at TIMESTAMPTZ DEFAULT NOW())", "CREATE TABLE IF NOT EXISTS nexus_staff_tasks(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,assignee_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,details TEXT,due_at TIMESTAMPTZ,status TEXT DEFAULT 'open',created_at TIMESTAMPTZ DEFAULT NOW())", "CREATE TABLE IF NOT EXISTS nexus_events(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,description TEXT,channel_id BIGINT,ends_at TIMESTAMPTZ,status TEXT DEFAULT 'open',created_at TIMESTAMPTZ DEFAULT NOW())", 'CREATE TABLE IF NOT EXISTS nexus_raffle_entries(event_id BIGINT NOT NULL,user_id BIGINT NOT NULL,PRIMARY KEY(event_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_afk(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,reason TEXT,since TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_quarantine(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,active BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW(),released_at TIMESTAMPTZ,release_by BIGINT,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_invites(guild_id BIGINT NOT NULL,code TEXT NOT NULL,uses INTEGER NOT NULL DEFAULT 0,inviter_id BIGINT,PRIMARY KEY(guild_id,code))', 'CREATE TABLE IF NOT EXISTS nexus_coupons(guild_id BIGINT NOT NULL,code TEXT NOT NULL,discount_percent INTEGER NOT NULL,active BOOLEAN DEFAULT TRUE,expires_at TIMESTAMPTZ,PRIMARY KEY(guild_id,code))', 'CREATE TABLE IF NOT EXISTS nexus_announcements(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,content TEXT NOT NULL,send_at TIMESTAMPTZ NOT NULL,sent BOOLEAN DEFAULT FALSE,created_by BIGINT NOT NULL)', 'CREATE TABLE IF NOT EXISTS nexus_custom_commands(guild_id BIGINT NOT NULL,name TEXT NOT NULL,response TEXT NOT NULL,created_by BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),updated_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,name))', 'CREATE TABLE IF NOT EXISTS nexus_reminders(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,channel_id BIGINT,message TEXT NOT NULL,due_at TIMESTAMPTZ NOT NULL,sent BOOLEAN NOT NULL DEFAULT FALSE,delivered BOOLEAN,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS nexus_staff_notes(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,author_id BIGINT NOT NULL,note TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS nexus_birthdays(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,month INTEGER NOT NULL,day INTEGER NOT NULL,last_year INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_tags(guild_id BIGINT NOT NULL,name TEXT NOT NULL,content TEXT NOT NULL,owner_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),updated_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,name))', 'CREATE TABLE IF NOT EXISTS nexus_starboard(guild_id BIGINT NOT NULL,source_message_id BIGINT NOT NULL,board_message_id BIGINT NOT NULL,source_channel_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,source_message_id))', 'CREATE TABLE IF NOT EXISTS nexus_level_rewards(guild_id BIGINT NOT NULL,level INTEGER NOT NULL,role_id BIGINT NOT NULL,PRIMARY KEY(guild_id,level))', 'CREATE TABLE IF NOT EXISTS nexus_polls(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,question TEXT NOT NULL,options TEXT[] NOT NULL,end_at TIMESTAMPTZ NOT NULL,message_id BIGINT,ended BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ DEFAULT NOW())', "CREATE TABLE IF NOT EXISTS nexus_applications(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,area TEXT NOT NULL,experience TEXT NOT NULL,availability TEXT NOT NULL,motivation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,review_note TEXT,created_at TIMESTAMPTZ DEFAULT NOW(),decided_at TIMESTAMPTZ)", 'CREATE TABLE IF NOT EXISTS nexus_reaction_roles(guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,message_id BIGINT NOT NULL,emoji TEXT NOT NULL,role_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,message_id,emoji))', 'CREATE TABLE IF NOT EXISTS nexus_invite_stats(guild_id BIGINT NOT NULL,inviter_id BIGINT NOT NULL,joins INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,inviter_id))', "CREATE TABLE IF NOT EXISTS nexus_virtual_items(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,name TEXT NOT NULL,description TEXT DEFAULT '',price BIGINT NOT NULL,stock INTEGER NOT NULL DEFAULT 0,consumable BOOLEAN NOT NULL DEFAULT TRUE,active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW())", 'CREATE TABLE IF NOT EXISTS nexus_inventory(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,item_id BIGINT NOT NULL,quantity INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id,item_id))', 'CREATE TABLE IF NOT EXISTS nexus_lockdown(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,actor_id BIGINT NOT NULL,scope TEXT NOT NULL,reason TEXT NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW(),ended_at TIMESTAMPTZ,end_actor BIGINT,end_reason TEXT)', 'CREATE TABLE IF NOT EXISTS nexus_lockdown_overwrites(guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,snapshot JSONB NOT NULL,PRIMARY KEY(guild_id,channel_id))', 'CREATE TABLE IF NOT EXISTS nexus_event_rsvps(guild_id BIGINT NOT NULL,event_id BIGINT NOT NULL,user_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,event_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_member_role_snapshots(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,roles BIGINT[] NOT NULL,created_by BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS nexus_temp_bans(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,case_id BIGINT NOT NULL,expires_at TIMESTAMPTZ NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,reason TEXT,created_at TIMESTAMPTZ DEFAULT NOW(),ended_at TIMESTAMPTZ,end_reason TEXT,PRIMARY KEY(guild_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_temp_roles(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,role_id BIGINT NOT NULL,expires_at TIMESTAMPTZ NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,reason TEXT,created_at TIMESTAMPTZ DEFAULT NOW(),ended_at TIMESTAMPTZ,PRIMARY KEY(guild_id,user_id,role_id))', "CREATE TABLE IF NOT EXISTS nexus_staff_meetings(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,agenda TEXT,channel_id BIGINT NOT NULL,scheduled_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL DEFAULT 'scheduled',created_at TIMESTAMPTZ DEFAULT NOW(),ended_at TIMESTAMPTZ,end_note TEXT)", 'CREATE TABLE IF NOT EXISTS nexus_staff_meeting_attendance(guild_id BIGINT NOT NULL,meeting_id BIGINT NOT NULL,user_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,meeting_id,user_id))', 'CREATE TABLE IF NOT EXISTS nexus_staff_activity(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,activity_date DATE NOT NULL,messages INTEGER NOT NULL DEFAULT 0,commands INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id,activity_date))', 'CREATE TABLE IF NOT EXISTS nexus_staff_goals(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,week_start DATE NOT NULL,message_goal INTEGER NOT NULL,command_goal INTEGER NOT NULL,created_by BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS nexus_recurring_announcements(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,interval_minutes INTEGER NOT NULL,next_run TIMESTAMPTZ NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,last_sent TIMESTAMPTZ,created_at TIMESTAMPTZ DEFAULT NOW())', 'CREATE TABLE IF NOT EXISTS nexus_moderation_templates(guild_id BIGINT NOT NULL,name TEXT NOT NULL,text TEXT NOT NULL,created_by BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),updated_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,name))', 'CREATE TABLE IF NOT EXISTS sistemas_suggestion_votes(guild_id BIGINT NOT NULL,suggestion_id BIGINT NOT NULL,user_id BIGINT NOT NULL,choice TEXT NOT NULL,updated_at TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,suggestion_id,user_id))']
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for q in ddl:
                    await conn.execute(q)
                safe_migrations = ['ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS evidence_attachment_url TEXT', 'ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS occurred TEXT', 'ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS witnesses TEXT', 'ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS review_message_id BIGINT', 'ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS duration_minutes INTEGER', 'ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS review_message_id BIGINT', 'ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS decision_reason TEXT', 'ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ', 'ALTER TABLE sistemas_staff ADD COLUMN IF NOT EXISTS role_name TEXT', 'ALTER TABLE sistemas_suggestions ADD COLUMN IF NOT EXISTS message_id BIGINT']
                for q in safe_migrations:
                    await conn.execute(q)
                await conn.execute('CREATE INDEX IF NOT EXISTS sistemas_cases_guild_user_idx ON sistemas_cases(guild_id,user_id,id DESC)')
                await conn.execute('CREATE INDEX IF NOT EXISTS sistemas_audit_guild_idx ON sistemas_audit(guild_id,id DESC)')
                await conn.execute('CREATE INDEX IF NOT EXISTS nexus_quarantine_expiry_idx ON nexus_quarantine(active,expires_at)')

    async def config(self, gid):
        r = await self.pool.fetchrow('SELECT data FROM sistemas_config WHERE guild_id=$1', gid)
        d = dict(DEFAULTS)
        if r:
            v = r['data']
            d.update(json.loads(v) if isinstance(v, str) else dict(v))
        return d

    async def setcfg(self, gid, key, value):
        if key not in DEFAULTS:
            raise ValueError('Config key not whitelisted')
        d = await self.config(gid)
        d[key] = value
        await self.pool.execute('INSERT INTO sistemas_config(guild_id,data) VALUES($1,$2::jsonb) ON CONFLICT(guild_id) DO UPDATE SET data=EXCLUDED.data,updated_at=NOW()', gid, json.dumps(d, ensure_ascii=False))

    async def audit(self, guild, actor, action, details, logkey='log_internal_channel_id', color=PURPLE):
        safe = {str(k): clip(v, 600) for k, v in details.items() if v is not None}
        await self.pool.execute('INSERT INTO sistemas_audit(guild_id,actor_id,action,details) VALUES($1,$2,$3,$4::jsonb)', guild.id, actor, action, json.dumps(safe, ensure_ascii=False))
        cfg = await self.config(guild.id)
        ch = guild.get_channel(cfg.get(logkey)) if cfg.get(logkey) else None
        if ch:
            e = embed(f"{EMOJI['pin']} {action}", '\n'.join((f"**{k.replace('_', ' ').title()}:** {v}" for k, v in safe.items())), color)
            if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
                e.set_image(url=cfg['theme_image_url'])
            try:
                await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                log.exception('Falha no log de guild %s', guild.id)

    async def dm(self, user, action, reason, case_id=None, duration=None):
        try:
            e = embed('NEXUS • Registro de moderação', f"**Ação:** {action}\n**Motivo:** {clip(reason, 1200)}\n**Registro:** #{case_id or '—'}\n**Duração:** {duration or 'Não aplicável'}\n\nSe acredita que houve engano, procure a equipe ou use o canal de apelações configurado.")
            await user.send(embed=e)
        except (discord.Forbidden, discord.HTTPException):
            log.info('DM indisponível para user id=%s', user.id)

    async def case(self, gid, uid, mid, action, reason, expiry=None):
        return await self.pool.fetchval('INSERT INTO sistemas_cases(guild_id,user_id,moderator_id,action,reason,expires_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', gid, uid, mid, action, reason, expiry)

    async def punish(self, guild, targetid, actor, kind, reason, minutes=None):
        botm = guild.me
        target = guild.get_member(targetid)
        cfg = await self.config(guild.id)
        if target:
            ok, msg = hierarchy(actor, target, botm)
            if not ok:
                raise ValueError(msg)
        if kind not in ('warn', 'timeout', 'mute', 'kick', 'ban', 'hackban', 'quarentena'):
            raise ValueError('Tipo de punição inválido')
        expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes) if minutes else None
        if kind in ('timeout', 'mute'):
            if not target:
                raise ValueError('Membro não está no servidor')
            if not minutes or minutes < 1 or minutes > 40320:
                raise ValueError('Timeout exige duração 1–40320 minutos')
            await target.timeout(timedelta(minutes=minutes), reason=reason)
        elif kind == 'kick':
            if not target:
                raise ValueError('Membro não está no servidor')
            await target.kick(reason=reason)
        elif kind in ('ban', 'hackban'):
            await guild.ban(target or discord.Object(id=targetid), reason=reason, delete_message_seconds=0)
        elif kind == 'quarentena':
            if not target:
                raise ValueError('Membro não está no servidor')
            role = guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None
            if not role:
                raise ValueError('Configure cargo de quarentena em /nexus_config')
            await target.add_roles(role, reason=reason)
            await self.pool.execute('INSERT INTO nexus_quarantine(guild_id,user_id,moderator_id,reason,expires_at,active) VALUES($1,$2,$3,$4,$5,TRUE) ON CONFLICT(guild_id,user_id) DO UPDATE SET moderator_id=EXCLUDED.moderator_id,reason=EXCLUDED.reason,expires_at=EXCLUDED.expires_at,active=TRUE,created_at=NOW()', guild.id, targetid, actor.id, reason, expiry)
        caseid = await self.case(guild.id, targetid, actor.id, kind, reason, expiry)
        try:
            user = target or await self.bot.fetch_user(targetid)
        except discord.HTTPException:
            user = None
        if user:
            await self.dm(user, kind, reason, caseid, f'{minutes} min' if minutes else None)
        await self.audit(guild, actor.id, 'Punição aplicada', {'case_id': caseid, 'target_id': targetid, 'tipo': kind, 'motivo': reason, 'duration_minutes': minutes}, 'log_punishment_channel_id', RED)
        return caseid

    async def create_request(self, guild, requester, targetid, kind, reason, occurred='', witnesses=None, evidence=None, minutes=None):
        rid = await self.pool.fetchval('INSERT INTO sistemas_requests(guild_id,requester_id,target_id,kind,reason,occurred,witnesses,evidence_url,duration_minutes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id', guild.id, requester.id, targetid, kind, reason, occurred, witnesses, evidence, minutes)
        cfg = await self.config(guild.id)
        ch = guild.get_channel(cfg.get('request_channel_id')) if cfg.get('request_channel_id') else None
        if ch:
            e = embed(f'⚖️ Solicitação de punição • #{rid}', 'Solicitação pendente de análise. IDs persistentes são usados para as ações dos botões.')
            e.add_field(name='Solicitante', value=f'{requester.mention} (`{requester.id}`)', inline=False)
            e.add_field(name='Alvo', value=f'<@{targetid}> (`{targetid}`)', inline=False)
            e.add_field(name='Ação', value=kind, inline=True)
            e.add_field(name='Motivo', value=clip(reason, 1000), inline=False)
            e.add_field(name='Data/ocorrido', value=occurred or '—', inline=True)
            e.add_field(name='Testemunhas', value=witnesses or '—', inline=True)
            e.add_field(name='Provas', value=evidence or '—', inline=False)
            msg = await ch.send(embed=e, view=RequestDecisionView(rid), allowed_mentions=discord.AllowedMentions.none())
            await self.pool.execute('UPDATE sistemas_requests SET review_message_id=$1 WHERE id=$2', msg.id, rid)
        await self.audit(guild, requester.id, 'Solicitação de punição registrada', {'request_id': rid, 'target_id': targetid, 'kind': kind}, 'log_internal_channel_id')
        return rid

    async def decision(self, inter, rid, status, reason='Decisão registrada'):
        row = await self.pool.fetchrow('SELECT * FROM sistemas_requests WHERE id=$1 AND guild_id=$2 FOR UPDATE', rid, inter.guild.id)
        if not row or row['status'] != 'pending':
            return await reply(inter, 'Solicitação já decidida ou não encontrada.')
        cfg = await self.config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Sem autorização para revisar solicitações.')
        await self.pool.execute("UPDATE sistemas_requests SET status=$1,reviewer_id=$2,decision_reason=$3,decided_at=NOW() WHERE id=$4 AND status='pending'", status, inter.user.id, reason, rid)
        applied = None
        if status == 'approved' and row['kind'] in set(cfg.get('request_auto_types') or []):
            try:
                applied = await self.punish(inter.guild, row['target_id'], inter.user, row['kind'], row['reason'], row['duration_minutes'])
            except Exception as exc:
                await reply(inter, f'Aprovado, mas execução falhou: {clip(exc, 250)}')
                return
        if inter.message and inter.message.embeds:
            e = inter.message.embeds[0]
            e.color = GREEN if status == 'approved' else RED
            e.add_field(name='Decisão', value=f'{status} por {inter.user.mention}\n{reason}', inline=False)
            e.add_field(name='Aplicação automática', value=f'Caso #{applied}' if applied else 'Não executada (manual/configuração)', inline=False)
            await inter.message.edit(embed=e, view=None)
        await self.audit(inter.guild, inter.user.id, 'Solicitação decidida', {'request_id': rid, 'status': status, 'reason': reason}, 'log_internal_channel_id')
        await reply(inter, 'Decisão registrada com sucesso.')

    async def create_appeal(self, inter, caseid, explanation, evidence=None):
        case = await self.pool.fetchrow('SELECT * FROM sistemas_cases WHERE id=$1 AND guild_id=$2 AND user_id=$3', caseid, inter.guild.id, inter.user.id)
        if not case:
            return await reply(inter, 'Punição não encontrada para seu ID neste servidor.')
        aid = await self.pool.fetchval('INSERT INTO sistemas_appeals(guild_id,case_id,appellant_id,explanation,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id', inter.guild.id, caseid, inter.user.id, explanation, evidence)
        cfg = await self.config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('appeal_channel_id')) if cfg.get('appeal_channel_id') else None
        if ch:
            e = embed(f'📨 Apelação • #{aid}', f'Caso de punição #{caseid}')
            e.add_field(name='Solicitante', value=f'{inter.user.mention} ({inter.user.id})', inline=False)
            e.add_field(name='Explicação', value=clip(explanation, 1200), inline=False)
            e.add_field(name='Provas', value=evidence or '—', inline=False)
            m = await ch.send(embed=e, view=AppealDecisionView(aid))
            await self.pool.execute('UPDATE sistemas_appeals SET review_message_id=$1 WHERE id=$2', m.id, aid)
        await self.audit(inter.guild, inter.user.id, 'Apelação registrada', {'appeal_id': aid, 'case_id': caseid}, 'log_internal_channel_id')
        await reply(inter, f'Apelação registrada: **#{aid}**')

    async def appeal_decision(self, inter, aid, status, reason):
        row = await self.pool.fetchrow("SELECT * FROM sistemas_appeals WHERE id=$1 AND guild_id=$2 AND status='pending'", aid, inter.guild.id)
        cfg = await self.config(inter.guild.id)
        if not row:
            return await reply(inter, 'Apelação já decidida ou não encontrada.')
        if not staff(inter.user, cfg):
            return await reply(inter, 'Sem autorização.')
        await self.pool.execute('UPDATE sistemas_appeals SET status=$1,reviewer_id=$2,decision_reason=$3,decided_at=NOW() WHERE id=$4', status, inter.user.id, reason, aid)
        if status == 'approved':
            await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE id=$1 AND guild_id=$2', row['case_id'], inter.guild.id)
        try:
            u = await self.bot.fetch_user(row['appellant_id'])
            await u.send(embed=embed('Nexus • Resultado da apelação', f'Apelação **#{aid}**: **{status}**\nJustificativa: {reason}'))
        except discord.HTTPException:
            pass
        await self.audit(inter.guild, inter.user.id, 'Apelação decidida', {'appeal_id': aid, 'status': status, 'reason': reason}, 'log_internal_channel_id')
        await reply(inter, 'Decisão de apelação registrada.')

    async def quarantine_release(self, guild, user_id, actorid, reason):
        cfg = await self.config(guild.id)
        role = guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None
        member = guild.get_member(user_id)
        if member and role:
            await member.remove_roles(role, reason=reason)
        await self.pool.execute('UPDATE nexus_quarantine SET active=FALSE,released_at=NOW(),release_by=$3 WHERE guild_id=$1 AND user_id=$2 AND active=TRUE', guild.id, user_id, actorid)
        await self.audit(guild, actorid, 'Quarentena removida', {'user_id': user_id, 'reason': reason}, 'log_punishment_channel_id', GREEN)

    @tasks.loop(minutes=1)
    async def expiry_loop(self):
        await self.bot.wait_until_ready()
        rows = await self.pool.fetch('SELECT guild_id,user_id FROM nexus_quarantine WHERE active=TRUE AND expires_at<=NOW()')
        for r in rows:
            g = self.bot.get_guild(r['guild_id'])
            if g:
                try:
                    await self.quarantine_release(g, r['user_id'], self.bot.user.id, 'Expiração automática')
                except Exception:
                    log.exception('Quarantine expiry failure guild=%s user=%s', g.id, r['user_id'])
        pending = await self.pool.fetch('SELECT id,guild_id,channel_id,content,send_at FROM nexus_announcements WHERE sent=FALSE AND send_at<=NOW()')
        for r in pending:
            g = self.bot.get_guild(r['guild_id'])
            ch = g.get_channel(r['channel_id']) if g else None
            if ch:
                try:
                    await ch.send(r['content'], allowed_mentions=discord.AllowedMentions.none())
                    await self.pool.execute('UPDATE nexus_announcements SET sent=TRUE WHERE id=$1', r['id'])
                except discord.HTTPException:
                    log.exception('Scheduled announcement failed id=%s', r['id'])

    @expiry_loop.before_loop
    async def before_expiry(self):
        await self.bot.wait_until_ready()

    async def backup(self, gid):
        cfg = await self.config(gid)
        data = {'config': cfg}
        for table in ('sistemas_cases', 'sistemas_requests', 'sistemas_appeals', 'sistemas_audit', 'sistemas_reports', 'sistemas_suggestions', 'sistemas_xp', 'nexus_quarantine', 'nexus_wallets', 'nexus_economy_tx'):
            rows = await self.pool.fetch(f'SELECT * FROM {table} WHERE guild_id=$1 ORDER BY 1', gid)
            data[table] = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in dict(row).items()} for row in rows]
        await self.pool.execute('INSERT INTO sistemas_backups(guild_id,payload) VALUES($1,$2::jsonb)', gid, json.dumps(data, default=str, ensure_ascii=False))

    @tasks.loop(hours=24)
    async def backup_loop(self):
        await self.bot.wait_until_ready()
        for g in self.bot.guilds:
            try:
                await self.backup(g.id)
            except Exception:
                log.exception('Backup failed guild=%s', g.id)

    @backup_loop.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot or not msg.guild:
            return
        cfg = await self.config(msg.guild.id)
        links = bool(re.search('https?://|discord\\.gg/|discord\\.com/invite/', msg.content, re.I))
        invites = bool(re.search('discord\\.gg/|discord\\.com/invite/', msg.content, re.I))
        words = [str(w).lower() for w in cfg.get('filter_words') or []]
        bypass = staff(msg.author, cfg) or any((role.id in set(cfg.get('automod_bypass_role_ids') or []) for role in msg.author.roles))
        violation = not bypass and (cfg.get('anti_links_enabled') and links or (cfg.get('anti_invites_enabled') and invites) or any((w and w in msg.content.lower() for w in words)) or (len(msg.mentions) + len(msg.role_mentions) > int(cfg.get('max_mentions', 5))))
        if violation:
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
            await self.audit(msg.guild, msg.author.id, 'AutoMod: mensagem removida', {'channel_id': msg.channel.id, 'message_id': msg.id, 'type': 'filter'}, 'log_internal_channel_id', GOLD)
            return
        if cfg.get('anti_spam_enabled') and (not bypass):
            q = self.msg_windows[msg.guild.id, msg.author.id]
            now = time.monotonic()
            q.append((now, msg.content))
            while q and now - q[0][0] > int(cfg.get('spam_window', 8)):
                q.popleft()
            repeated = len(q) >= int(cfg.get('spam_count', 5)) and len({x[1] for x in q}) <= 2
            if len(q) >= int(cfg.get('spam_count', 5)) or repeated:
                try:
                    await msg.delete()
                except discord.HTTPException:
                    pass
                await self.audit(msg.guild, msg.author.id, 'AutoMod: spam/flood', {'channel_id': msg.channel.id, 'count': len(q)}, 'log_internal_channel_id', GOLD)
                q.clear()
                return
        for m in msg.mentions:
            row = await self.pool.fetchrow('SELECT reason,since FROM nexus_afk WHERE guild_id=$1 AND user_id=$2', msg.guild.id, m.id)
            if row:
                await msg.reply(embed=embed('AFK • Membro ausente', f"{m.mention} está ausente: {clip(row['reason'] or 'Sem motivo', 250)}"), delete_after=12)
        afk = await self.pool.fetchrow('SELECT reason FROM nexus_afk WHERE guild_id=$1 AND user_id=$2', msg.guild.id, msg.author.id)
        if afk:
            await self.pool.execute('DELETE FROM nexus_afk WHERE guild_id=$1 AND user_id=$2', msg.guild.id, msg.author.id)
            await msg.reply(embed=embed('Bem-vindo de volta!', f'{msg.author.mention}, seu status AFK foi removido.'), delete_after=10)
        if cfg.get('xp_enabled'):
            row = await self.pool.fetchrow('SELECT xp,level,last_message_at FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2', msg.guild.id, msg.author.id)
            if not row or not row['last_message_at'] or (datetime.now(timezone.utc) - row['last_message_at']).total_seconds() >= int(cfg.get('xp_cooldown', 60)):
                add = 5
                xp = (row['xp'] if row else 0) + add
                level = int(xp ** 0.5 // 5)
                await self.pool.execute('INSERT INTO sistemas_xp(guild_id,user_id,xp,level,last_message_at) VALUES($1,$2,$3,$4,NOW()) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=EXCLUDED.xp,level=EXCLUDED.level,last_message_at=NOW()', msg.guild.id, msg.author.id, xp, level)
                if row and level > row['level']:
                    await msg.channel.send(embed=embed('✨ Level up!', f'{msg.author.mention} alcançou o nível **{level}**!'), delete_after=12)
                    reward = await self.pool.fetchrow('SELECT role_id FROM nexus_level_rewards WHERE guild_id=$1 AND level=$2', msg.guild.id, level)
                    if reward:
                        role = msg.guild.get_role(reward['role_id'])
                        if role and role < msg.guild.me.top_role:
                            try:
                                await msg.author.add_roles(role, reason=f'Nexus level reward {level}')
                            except discord.HTTPException:
                                pass
        if msg.content.startswith('.'):
            raw = msg.content[1:].strip()
            name = raw.split(maxsplit=1)[0].lower() if raw else ''
            if name in ('nexus', 'painelnexus', 'painel'):
                await self.send_public_panel(msg.channel, msg.author)
            elif name == 'afk':
                await self.afk_prefix_action(msg, raw[4:].strip() or 'Ausente')
            elif name == 'afk_sair':
                vc = msg.guild.voice_client
                if vc:
                    await vc.disconnect(force=True)
                    await msg.reply('Bot saiu da call.')
            elif name == 'mod' and staff(msg.author, cfg):
                await msg.reply(embed=self.moderation_menu(msg.guild))
            elif name == 'logs' and staff(msg.author, cfg):
                await self.logs_prefix(msg, int(raw.split()[1]) if len(raw.split()) > 1 and raw.split()[1].isdigit() else 10)
            elif name == 'quarentena' and staff(msg.author, cfg):
                args = raw.split(maxsplit=2)
                if len(args) >= 2 and args[1].isdigit():
                    targetid = int(args[1])
                    reason = args[2] if len(args) > 2 else 'Quarentena aplicada pela equipe'
                    try:
                        caseid = await self.punish(msg.guild, targetid, msg.author, 'quarentena', reason, None)
                        await msg.reply(f'Quarentena aplicada. Caso #{caseid}')
                    except Exception as ex:
                        await msg.reply(f'Falhou: {clip(ex, 250)}')
            elif name in ('ban', 'kick', 'warn', 'mute', 'hackban'):
                args = raw.split(maxsplit=3)
                if len(args) >= 2:
                    uidmatch = re.search('\\d{15,22}', args[1])
                    targetid = int(uidmatch.group()) if uidmatch else 0
                    duration = None
                    reason = 'Sem motivo informado'
                    if name == 'mute' and len(args) >= 3 and args[2].isdigit():
                        duration = int(args[2])
                        reason = args[3] if len(args) > 3 else reason
                    elif len(args) >= 3:
                        reason = args[2] + ' ' + (args[3] if len(args) > 3 else '')
                    required = {'ban': 'ban_members', 'hackban': 'ban_members', 'kick': 'kick_members', 'mute': 'moderate_members', 'warn': 'moderate_members'}[name]
                    if targetid:
                        if not staff(msg.author, cfg) and (not getattr(msg.author.guild_permissions, required, False)):
                            await msg.reply('Sem permissão para essa punição.')
                        else:
                            try:
                                caseid = await self.punish(msg.guild, targetid, msg.author, 'timeout' if name == 'mute' else name, reason.strip(), duration)
                                await msg.reply(f'Punição aplicada e registrada no caso #{caseid}.')
                            except Exception as ex:
                                await msg.reply(f'Falha: {clip(ex, 250)}')
            elif name == 'liberar' and staff(msg.author, cfg):
                args = raw.split(maxsplit=2)
                if len(args) > 1 and args[1].isdigit():
                    await self.quarantine_release(msg.guild, int(args[1]), msg.author.id, args[2] if len(args) > 2 else 'Liberação manual')
                    await msg.reply('Liberação processada.')
            elif name == 'wallet':
                await msg.reply(embed=await self.wallet_embed(msg.guild, msg.author.id))
            elif name == 'daily':
                await self.daily(msg.guild, msg.author)
            elif name == 'work':
                await self.work(msg.guild, msg.author)
            elif name == 'pay':
                await self.pay_prefix(msg)
            elif name == 'rank':
                await self.rank_prefix(msg)
            elif name == 'shop':
                await self.shop_prefix(msg)
            elif name == 'help':
                await msg.reply(embed=self.help_embed())
            else:
                custom = await self.pool.fetchrow('SELECT response FROM nexus_custom_commands WHERE guild_id=$1 AND name=$2', msg.guild.id, name)
                if custom:
                    text = str(custom['response']).replace('{member}', msg.author.mention).replace('{server}', msg.guild.name).replace('{user}', msg.author.display_name)
                    await msg.reply(clip(text, 1900), allowed_mentions=discord.AllowedMentions.none())

    async def afk_prefix_action(self, msg, reason):
        member = msg.author
        if not member.voice or not member.voice.channel:
            return await msg.reply('Entre em um canal de voz primeiro para usar AFK call.')
        vc = msg.guild.voice_client
        if vc:
            await vc.move_to(member.voice.channel)
        else:
            await member.voice.channel.connect(self_deaf=True, self_mute=True)
        await self.pool.execute('INSERT INTO nexus_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()', msg.guild.id, member.id, reason)
        await msg.reply(f'AFK ativado; bot na call **{member.voice.channel.name}**. Use `.afk_sair` para desconectar.')

    async def send_public_panel(self, channel, author):
        cfg = await self.config(channel.guild.id)
        e = embed('NEXUS • CENTRAL DE SISTEMAS', 'Uma central organizada de utilidades, comunidade e administração.\n\n**Moderação:** denúncias, punições, revisão e histórico.\n**Comunidade:** sugestões, XP, eventos e sorteios.\n**Economia:** carteira, diario, trabalho e transferências.\n**Equipe:** tarefas, status e acompanhamento.\n**Segurança:** automod, anti-raid, anti-nuke e quarentena.\n\nUse os comandos `.help` ou `/nexus` para acessar as ferramentas.', PURPLE)
        e.set_thumbnail(url=VISUALS['shield'])
        e.set_image(url=cfg.get('theme_image_url') or VISUALS['banner'])
        await channel.send(embed=e, view=NexusPublicPanel())

    def moderation_menu(self, guild):
        e = embed('NEXUS • MODERAÇÃO', 'Comandos: `.ban @membro motivo`, `.kick @membro motivo`, `.warn @membro motivo` (slash), `.mute @membro minutos motivo`, `.quarentena ID motivo`, `.liberar ID motivo`, `.logs [limite]`.')
        return e

    async def logs_prefix(self, msg, limit):
        rows = await self.pool.fetch('SELECT id,actor_id,action,details,created_at FROM sistemas_audit WHERE guild_id=$1 ORDER BY id DESC LIMIT $2', msg.guild.id, max(1, min(20, limit)))
        e = embed('NEXUS • AUDITORIA', f'{len(rows)} registros recentes')
        for r in rows:
            d = r['details'] if isinstance(r['details'], dict) else json.loads(r['details'] or '{}')
            e.add_field(name=f"#{r['id']} {r['action']}", value=clip(f"Autor: <@{r['actor_id']}>\n{d}\n<t:{int(r['created_at'].timestamp())}:R>", 850), inline=False)
        await msg.reply(embed=e)

    async def wallet_embed(self, guild, uid):
        bal = await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2', guild.id, uid) or 0
        return embed('NEXUS • CARTEIRA', f'<@{uid}> possui **{bal:,} NXC** na economia virtual.\n\nEconomia virtual não representa dinheiro real e não tem conversão ou pagamento externo.')

    async def ensure_wallet(self, gid, uid):
        await self.pool.execute('INSERT INTO nexus_wallets(guild_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING', gid, uid)

    async def daily(self, guild, user):
        await self.ensure_wallet(guild.id, user.id)
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock($1)', user.id)
                exists = await c.fetchval("SELECT 1 FROM nexus_economy_tx WHERE guild_id=$1 AND to_user=$2 AND kind=$3 AND created_at >= date_trunc('day',NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'", guild.id, user.id, 'daily')
                if exists:
                    try:
                        await user.send('Você já recebeu seu diario hoje.')
                    except discord.HTTPException:
                        pass
                    return
                amt = int((await self.config(guild.id)).get('economy_daily', 100))
                await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2', guild.id, user.id, amt)
                await c.execute('INSERT INTO nexus_economy_tx(guild_id,to_user,amount,kind) VALUES($1,$2,$3,$4)', guild.id, user.id, amt, 'daily')
        try:
            await user.send(embed=embed('NEXUS • Recompensa diária', f'Você recebeu **{amt} NXC**.'))
        except discord.HTTPException:
            pass
        return True

    async def work(self, guild, user):
        await self.ensure_wallet(guild.id, user.id)
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock($1)', user.id)
                cooldown = int((await self.config(guild.id)).get('economy_cooldown', 3600))
                recent = await c.fetchval("SELECT 1 FROM nexus_economy_tx WHERE guild_id=$1 AND to_user=$2 AND kind='work' AND created_at>NOW()-($3 * INTERVAL '1 second')", guild.id, user.id, cooldown)
                if recent:
                    try:
                        await user.send(f'Trabalho em cooldown; aguarde {cooldown // 60} minutos.')
                    except discord.HTTPException:
                        pass
                    return False
                cfg = await self.config(guild.id)
                amount = __import__('random').randint(int(cfg.get('economy_work_min', 25)), int(cfg.get('economy_work_max', 100)))
                await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2', guild.id, user.id, amount)
                await c.execute('INSERT INTO nexus_economy_tx(guild_id,to_user,amount,kind) VALUES($1,$2,$3,$4)', guild.id, user.id, amount, 'work')
        try:
            await user.send(embed=embed('NEXUS • Trabalho', f'Você recebeu **{amount} NXC** por seu trabalho.'))
        except discord.HTTPException:
            pass
        return True

    async def pay_prefix(self, msg):
        parts = msg.content.split()
        if len(parts) < 3 or not parts[1].isdigit() or (not parts[2].isdigit()):
            return await msg.reply('Uso: `.pay ID quantidade`')
        uid, amount = (int(parts[1]), int(parts[2]))
        gid = msg.guild.id
        if uid == msg.author.id or amount <= 0:
            return await msg.reply('Destino/valor inválido.')
        await self.ensure_wallet(gid, msg.author.id)
        await self.ensure_wallet(gid, uid)
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock($1)', msg.author.id)
                bal = await c.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', gid, msg.author.id)
                if bal < amount:
                    return await msg.reply('Saldo insuficiente.')
                await c.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2', gid, msg.author.id, amount)
                await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2', gid, uid, amount)
                await c.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$3,$4,$5)', gid, msg.author.id, uid, amount, 'transfer')
        await msg.reply(f'Transferência de **{amount} NXC** para <@{uid}> concluída.')

    async def rank_prefix(self, msg):
        rows = await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10', msg.guild.id)
        e = embed('NEXUS • RANKING XP', 'Top 10 membros')
        for i, r in enumerate(rows, 1):
            e.add_field(name=f"{i}. <@{r['user_id']}>", value=f"{r['xp']} XP • nível {r['level']}", inline=False)
        await msg.reply(embed=e)

    async def shop_prefix(self, msg):
        rows = await self.pool.fetch('SELECT id,name,description,price_cents,stock FROM nexus_products WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 20', msg.guild.id)
        e = embed('NEXUS • LOJA', 'Produtos digitais/físicos configurados. Pagamentos externos não são habilitados sem credenciais e confirmação segura de provedor.')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['name']} • R$ {r['price_cents'] / 100:.2f}", value=f"{clip(r['description'], 200)}\nEstoque: {r['stock']}", inline=False)
        await msg.reply(embed=e)

    def help_embed(self):
        e = embed('NEXUS • COMANDOS', 'Prefixo principal para novos comandos: `.`. Comandos legados do ticket permanecem com `!` e slash.')
        e.add_field(name='Comunidade', value='`.nexus` • `.help` • `.rank` • `.suggest` (slash) • `/denunciar`', inline=False)
        e.add_field(name='Economia', value='`.wallet` • `.daily` • `.work` • `.pay ID valor` • `.shop`', inline=False)
        e.add_field(name='Moderação', value='`.mod` • `.quarentena ID motivo` • `.liberar ID motivo` • `.logs` • slash de punição', inline=False)
        e.add_field(name='AFK Call', value='`.afk motivo` (entra bot na call) • `.afk_sair`', inline=False)
        return e

    @app_commands.command(name='nexus', description='Abre o painel interativo Nexus.')
    async def nexus_cmd(self, inter):
        await inter.response.send_message(embed=embed('NEXUS • CENTRAL', 'Escolha a categoria pelos botões abaixo. Ações administrativas exigem autorização.'), view=NexusPublicPanel(), ephemeral=True)

    @app_commands.command(name='nexus_config', description='Configuração segura do Nexus para este servidor.')
    @app_commands.checks.has_permissions(administrator=True)
    async def nexus_config(self, inter, staff_role: Optional[discord.Role]=None, quarantine_role: Optional[discord.Role]=None, request_channel: Optional[discord.TextChannel]=None, appeal_channel: Optional[discord.TextChannel]=None, report_channel: Optional[discord.TextChannel]=None, suggestion_channel: Optional[discord.TextChannel]=None, remote_admin_ids: str=''):
        if staff_role:
            cfg = await self.config(inter.guild.id)
            roles = set(cfg.get('staff_role_ids') or [])
            roles.add(staff_role.id)
            await self.setcfg(inter.guild.id, 'staff_role_ids', sorted(roles))
        if quarantine_role:
            await self.setcfg(inter.guild.id, 'quarantine_role_id', quarantine_role.id)
        for k, v in [('request_channel_id', request_channel), ('appeal_channel_id', appeal_channel), ('report_channel_id', report_channel), ('suggestion_channel_id', suggestion_channel)]:
            if v:
                await self.setcfg(inter.guild.id, k, v.id)
        ids = []
        if remote_admin_ids.strip():
            try:
                ids = [int(x.strip()) for x in remote_admin_ids.split(',') if x.strip().isdigit()]
            except ValueError:
                return await reply(inter, 'IDs remotos inválidos.')
            await self.setcfg(inter.guild.id, 'remote_admin_ids', ids)
            await self.setcfg(inter.guild.id, 'remote_enabled', bool(ids))
        await self.audit(inter.guild, inter.user.id, 'Configuração Nexus atualizada', {'staff_role': staff_role.id if staff_role else None, 'quarantine_role': quarantine_role.id if quarantine_role else None, 'remote_ids': ids}, 'log_internal_channel_id')
        await reply(inter, 'Configurações aplicadas. Use `/nexus_config_logs` para ajustar os logs preservados.')

    @app_commands.command(name='nexus_config_logs', description='Configura canais de log por categoria.')
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs(self, inter, server_log: Optional[discord.TextChannel]=None, member_log: Optional[discord.TextChannel]=None, role_log: Optional[discord.TextChannel]=None, punishment_log: Optional[discord.TextChannel]=None, internal_log: Optional[discord.TextChannel]=None):
        for k, v in [('log_server_channel_id', server_log), ('log_member_channel_id', member_log), ('log_role_channel_id', role_log), ('log_punishment_channel_id', punishment_log), ('log_internal_channel_id', internal_log)]:
            if v:
                await self.setcfg(inter.guild.id, k, v.id)
        await reply(inter, 'Canais de logs atualizados (sistema de logs preservado e configurável).')

    @app_commands.command(name='painel_remoto', description='Painel remoto de controle dos servidores Nexus (somente IDs autorizados).')
    async def remote_panel(self, inter):
        allowed = set((int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS', '').split(',') if x.strip().isdigit()))
        if inter.user.id not in allowed:
            return await reply(inter, 'Acesso remoto negado. ID não autorizado na variável NEXUS_REMOTE_ADMIN_IDS.')
        await inter.response.send_message(embed=embed('NEXUS • REMOTE OPS', f'Servidores conectados: **{len(self.bot.guilds)}**\nSelecione uma ação abaixo.'), view=NexusRemotePanel(), ephemeral=True)

    @app_commands.command(name='punir', description='Aplicar punição com motivo e validação de hierarquia.')
    async def punish_cmd(self, inter, kind: str, user_id: str, reason: str, minutes: Optional[app_commands.Range[int, 1, 40320]]=None):
        cfg = await self.config(inter.guild.id)
        perms = {'ban': 'ban_members', 'hackban': 'ban_members', 'kick': 'kick_members', 'mute': 'moderate_members', 'timeout': 'moderate_members', 'warn': 'moderate_members', 'quarentena': 'manage_roles'}
        if not staff(inter.user, cfg) and (not getattr(inter.user.guild_permissions, perms.get(kind, 'moderate_members'), False)):
            return await reply(inter, 'Você não tem autorização para essa ação.')
        if not user_id.isdigit():
            return await reply(inter, 'ID de usuário inválido.')
        try:
            caseid = await self.punish(inter.guild, int(user_id), inter.user, kind, reason, minutes)
        except Exception as ex:
            return await reply(inter, f'Não foi possível aplicar: {clip(ex, 300)}')
        await reply(inter, f'{kind} executado e registrado. Caso **#{caseid}**.')

    @app_commands.command(name='historico_punicoes', description='Consultar histórico de punições.')
    async def history_cmd(self, inter, user: discord.User):
        cfg = await self.config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Somente equipe autorizada.')
        rows = await self.pool.fetch('SELECT id,action,reason,moderator_id,created_at,active,expires_at FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15', inter.guild.id, user.id)
        e = embed(f'NEXUS • HISTÓRICO {user}', f'{len(rows)} registros encontrados')
        for r in rows:
            e.add_field(name=f"Caso #{r['id']} • {r['action']} • {('ativo' if r['active'] else 'inativo')}", value=clip(f"{r['reason']}\nMod: <@{r['moderator_id']}> • <t:{int(r['created_at'].timestamp())}:R>", 700), inline=False)
        await reply(inter, em=e)

    @app_commands.command(name='quarentena_lista', description='Listar usuários em quarentena.')
    async def quarantine_list(self, inter):
        cfg = await self.config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Sem autorização.')
        rows = await self.pool.fetch('SELECT user_id,reason,moderator_id,expires_at,created_at FROM nexus_quarantine WHERE guild_id=$1 AND active=TRUE ORDER BY created_at DESC LIMIT 30', inter.guild.id)
        e = embed('NEXUS • QUARENTENA', f'{len(rows)} registros ativos')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}>", value=f"Motivo: {clip(r['reason'], 250)}\nResponsável: <@{r['moderator_id']}>\nExpira: {r['expires_at'] or 'Sem prazo'}", inline=False)
        await reply(inter, em=e)

    @app_commands.command(name='afk', description='Ativa status AFK e conecta o bot à sua call atual.')
    async def afk_slash(self, inter, reason: str='Ausente'):
        if not inter.user.voice or not inter.user.voice.channel:
            return await reply(inter, 'Entre em uma call primeiro.')
        try:
            vc = inter.guild.voice_client
            if vc:
                await vc.move_to(inter.user.voice.channel)
            else:
                await inter.user.voice.channel.connect(self_deaf=True, self_mute=True)
            await self.pool.execute('INSERT INTO nexus_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()', inter.guild.id, inter.user.id, reason)
            await reply(inter, f'Bot conectado a **{inter.user.voice.channel.name}** até comando de saída.')
        except discord.HTTPException as e:
            await reply(inter, f'Falha de voz: {clip(e, 200)}')

    @app_commands.command(name='afk_sair', description='Desconecta o bot da call AFK.')
    async def afk_leave_slash(self, inter):
        vc = inter.guild.voice_client
        if not vc:
            return await reply(inter, 'Bot não está conectado.')
        await vc.disconnect(force=True)
        await reply(inter, 'Desconectado da call.')

    @app_commands.command(name='denunciar', description='Enviar denúncia para a equipe.')
    async def report_slash(self, inter, target: discord.User, reason: str, evidence: Optional[str]=None):
        if evidence and (not url_ok(evidence)):
            return await reply(inter, 'URL inválida.')
        cfg = await self.config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('report_channel_id')) if cfg.get('report_channel_id') else None
        if not ch:
            return await reply(inter, 'Canal de denúncias não configurado por `/nexus_config`.')
        rid = await self.pool.fetchval('INSERT INTO sistemas_reports(guild_id,reporter_id,target_id,reason,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id', inter.guild.id, inter.user.id, target.id, reason, evidence)
        e = embed(f'NEXUS • DENÚNCIA #{rid}', 'Registro recebido para análise.')
        e.add_field(name='Autor', value=f'{inter.user} ({inter.user.id})')
        e.add_field(name='Alvo', value=f'{target} ({target.id})')
        e.add_field(name='Relato', value=clip(reason, 1000))
        e.add_field(name='Provas', value=evidence or '—')
        await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await self.audit(inter.guild, inter.user.id, 'Denúncia registrada', {'report_id': rid, 'target_id': target.id})
        await reply(inter, f'Denúncia enviada. Protocolo #{rid}.')

    @app_commands.command(name='sugerir', description='Enviar sugestão comunitária.')
    async def suggest_slash(self, inter, suggestion: str):
        cfg = await self.config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('suggestion_channel_id')) if cfg.get('suggestion_channel_id') else None
        if not ch:
            return await reply(inter, 'Configure o canal de sugestões em `/nexus_config`.')
        sid = await self.pool.fetchval('INSERT INTO sistemas_suggestions(guild_id,user_id,content) VALUES($1,$2,$3) RETURNING id', inter.guild.id, inter.user.id, suggestion)
        e = embed(f'💡 NEXUS • SUGESTÃO #{sid}', clip(suggestion, 3000))
        e.add_field(name='Autor', value=inter.user.mention)
        e.set_footer(text='NEXUS • Votos 👍 0 | 👎 0')
        m = await ch.send(embed=e, view=SuggestionVoteView(), allowed_mentions=discord.AllowedMentions.none())
        await self.pool.execute('UPDATE sistemas_suggestions SET message_id=$1 WHERE id=$2', m.id, sid)
        await reply(inter, f'Sugestão registrada #{sid}.')

    @app_commands.command(name='ranking_xp', description='Mostrar ranking XP da comunidade.')
    async def xp_rank_slash(self, inter):
        rows = await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10', inter.guild.id)
        e = embed('NEXUS • RANK XP', 'Top 10')
        for i, r in enumerate(rows, 1):
            e.add_field(name=f"{i}º • <@{r['user_id']}>", value=f"{r['xp']} XP • nível {r['level']}", inline=False)
        await reply(inter, em=e)

    @app_commands.command(name='solicitar_punicao', description='Enviar pedido de punição para revisão da equipe.')
    async def request_slash(self, inter, target: discord.User, kind: str, reason: str, occurred: str='', witnesses: str='', evidence: str='', minutes: Optional[app_commands.Range[int, 1, 40320]]=None):
        cfg = await self.config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Somente staff autorizada pode solicitar punições.')
        allowed = {'warn', 'timeout', 'mute', 'kick', 'ban', 'hackban', 'quarentena'}
        if kind not in allowed:
            return await reply(inter, 'Tipo inválido. Use warn, timeout, mute, kick, ban, hackban ou quarentena.')
        if kind in ('timeout', 'mute') and (not minutes):
            return await reply(inter, 'Timeout/mute precisa de duração (minutos).')
        if evidence and (not url_ok(evidence)):
            return await reply(inter, 'Link de prova deve ser URL http(s).')
        rid = await self.create_request(inter.guild, inter.user, target.id, kind, reason, occurred, witnesses or None, evidence or None, minutes)
        await reply(inter, f'Solicitação enviada para análise: **#{rid}**.')

    @app_commands.command(name='apelar_punicao', description='Solicitar revisão de uma punição aplicada ao seu usuário.')
    async def appeal_slash(self, inter, case_id: int, explanation: str, evidence: str=''):
        if evidence and (not url_ok(evidence)):
            return await reply(inter, 'URL de prova inválida.')
        await self.create_appeal(inter, case_id, explanation, evidence or None)

    @app_commands.command(name='quarentena_liberar', description='Liberar usuário da quarentena.')
    async def quarantine_release_slash(self, inter, user: discord.User, reason: str='Liberação manual'):
        cfg = await self.config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Sem autorização para liberar quarentena.')
        await self.quarantine_release(inter.guild, user.id, inter.user.id, reason)
        await reply(inter, 'Liberação concluída e registrada.')

    @app_commands.command(name='automod_config', description='Configurar automod, links, convites, spam e palavras proibidas.')
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_config(self, inter, spam: bool=False, links: bool=False, invites: bool=False, words: str='', mention_limit: app_commands.Range[int, 2, 20]=5):
        await self.setcfg(inter.guild.id, 'anti_spam_enabled', spam)
        await self.setcfg(inter.guild.id, 'anti_links_enabled', links)
        await self.setcfg(inter.guild.id, 'anti_invites_enabled', invites)
        await self.setcfg(inter.guild.id, 'filter_words', [w.strip().lower() for w in words.split('|') if w.strip()][:100])
        await self.setcfg(inter.guild.id, 'max_mentions', mention_limit)
        await self.audit(inter.guild, inter.user.id, 'Automod configurado', {'spam': spam, 'links': links, 'invites': invites, 'filter_word_count': len(words.split('|')), 'mention_limit': mention_limit})
        await reply(inter, 'AutoMod atualizado. Remoções são registradas; punições automáticas não estão ativadas por padrão.')

    @app_commands.command(name='config_protecao', description='Configurar alerta Anti-Raid/Anti-Nuke, limiares e IDs confiáveis.')
    @app_commands.checks.has_permissions(administrator=True)
    async def protection_config(self, inter, anti_raid: bool=False, anti_nuke: bool=False, raid_threshold: app_commands.Range[int, 3, 30]=6, window_seconds: app_commands.Range[int, 5, 60]=12, trusted_ids: str=''):
        await self.setcfg(inter.guild.id, 'anti_raid_enabled', anti_raid)
        await self.setcfg(inter.guild.id, 'anti_nuke_enabled', anti_nuke)
        await self.setcfg(inter.guild.id, 'anti_raid_threshold', raid_threshold)
        await self.setcfg(inter.guild.id, 'anti_raid_window_seconds', window_seconds)
        ids = [int(x.strip()) for x in trusted_ids.split(',') if x.strip().isdigit()][:100]
        await self.setcfg(inter.guild.id, 'trusted_admin_ids', ids)
        await self.audit(inter.guild, inter.user.id, 'Proteções configuradas', {'anti_raid': anti_raid, 'anti_nuke': anti_nuke, 'threshold': raid_threshold, 'window': window_seconds, 'trusted_ids': ids})
        await reply(inter, 'Configurações de proteção salvas. Proteções geram alertas; não executam ações destrutivas automáticas.')

    @app_commands.command(name='backup_manual', description='Criar backup JSON persistente do estado administrativo.')
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_manual_cmd(self, inter):
        await self.backup(inter.guild.id)
        await reply(inter, 'Backup criado no banco. Não contém tokens nem credenciais.')

    @app_commands.command(name='status_nexus', description='Status do bot, banco e módulos.')
    async def status_cmd(self, inter):
        cfg = await self.config(inter.guild.id)
        e = embed('NEXUS • STATUS', f'Uptime: <t:{int(datetime.now(timezone.utc).timestamp() - (time.monotonic() - self.started))}:R>\nLatência: **{self.bot.latency * 1000:.0f} ms**\nServidores: **{len(self.bot.guilds)}**\nMódulo Systems: **ativo**\nDB pool: **conectado** (consulta de teste abaixo)')
        try:
            await self.pool.fetchval('SELECT 1')
            e.add_field(name='Banco', value='PostgreSQL conectado', inline=False)
        except Exception:
            e.add_field(name='Banco', value='Falha de conexão', inline=False)
        await reply(inter, em=e)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        cfg = await self.config(member.guild.id)
        if cfg.get('anti_raid_enabled'):
            q = self.join_windows[member.guild.id]
            now = time.monotonic()
            q.append(now)
            win = int(cfg.get('anti_raid_window_seconds', 12))
            while q and now - q[0] > win:
                q.popleft()
            if len(q) >= int(cfg.get('anti_raid_threshold', 6)):
                await self.audit(member.guild, None, 'Alerta Anti-Raid', {'join_count': len(q), 'window_seconds': win, 'last_member_id': member.id}, 'log_internal_channel_id', RED)
                q.clear()
        await self.audit(member.guild, None, 'Membro entrou', {'user_id': member.id, 'account_created': member.created_at.isoformat()}, 'log_member_channel_id')
        wc = member.guild.get_channel(cfg.get('welcome_channel_id')) if cfg.get('welcome_channel_id') else None
        if wc:
            text = str(cfg.get('welcome_message') or 'Bem-vindo {member} ao {server}').replace('{member}', member.mention).replace('{server}', member.guild.name)
            e = embed('NEXUS • BOAS-VINDAS', text)
            e.set_thumbnail(url=member.display_avatar.url)
            await wc.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        role = member.guild.get_role(cfg.get('autorole_id')) if cfg.get('autorole_id') else None
        if role:
            try:
                await member.add_roles(role, reason='Autorole Nexus')
            except discord.HTTPException:
                log.warning('Autorole failed guild=%s member=%s', member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.audit(member.guild, None, 'Membro saiu', {'user_id': member.id, 'name': str(member)}, 'log_member_channel_id')

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.audit(guild, None, 'Ban registrado pelo Discord', {'user_id': user.id}, 'log_punishment_channel_id', RED)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.audit(guild, None, 'Desbanimento registrado', {'user_id': user.id}, 'log_punishment_channel_id', GREEN)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        cfg = await self.config(ch.guild.id)
        actor = None
        try:
            async for entry in ch.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
                if getattr(entry.target, 'id', None) == ch.id and (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 25:
                    actor = entry.user.id
                    break
        except discord.HTTPException:
            pass
        if cfg.get('anti_nuke_enabled') and actor and (actor not in cfg.get('trusted_admin_ids', [])) and (actor != self.bot.user.id):
            await self.audit(ch.guild, actor, 'ALERTA ANTI-NUKE • canal excluído', {'channel': ch.name, 'channel_id': ch.id}, 'log_internal_channel_id', RED)
        await self.audit(ch.guild, actor, 'Canal excluído', {'channel': ch.name, 'channel_id': ch.id}, 'log_server_channel_id', RED)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        cfg = await self.config(role.guild.id)
        actor = None
        try:
            async for entry in role.guild.audit_logs(limit=5, action=discord.AuditLogAction.role_delete):
                if getattr(entry.target, 'id', None) == role.id and (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 25:
                    actor = entry.user.id
                    break
        except discord.HTTPException:
            pass
        if cfg.get('anti_nuke_enabled') and actor and (actor not in cfg.get('trusted_admin_ids', [])) and (actor != self.bot.user.id):
            await self.audit(role.guild, actor, 'ALERTA ANTI-NUKE • cargo excluído', {'role': role.name, 'role_id': role.id}, 'log_internal_channel_id', RED)
        await self.audit(role.guild, actor, 'Cargo excluído', {'role': role.name, 'role_id': role.id}, 'log_role_channel_id', RED)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        cfg = await self.config(ch.guild.id)
        role = ch.guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None
        if role:
            try:
                await ch.set_permissions(role, view_channel=False, send_messages=False, connect=False, reason='Nexus quarantine role restriction')
            except discord.HTTPException:
                log.warning('Could not apply quarantine overwrite on new channel %s', ch.id)
        await self.audit(ch.guild, None, 'Canal criado', {'channel': ch.name, 'channel_id': ch.id}, 'log_server_channel_id')

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.audit(role.guild, None, 'Cargo criado', {'role': role.name, 'role_id': role.id}, 'log_role_channel_id')

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = {a: f'{getattr(before, a, None)} -> {getattr(after, a, None)}' for a in ('name', 'permissions', 'position', 'colour', 'hoist', 'mentionable') if getattr(before, a, None) != getattr(after, a, None)}
        if changes:
            await self.audit(after.guild, None, 'Cargo alterado', {'role': after.name, **changes}, 'log_role_channel_id')

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = {a: f'{getattr(before, a, None)} -> {getattr(after, a, None)}' for a in ('name', 'topic', 'slowmode_delay', 'nsfw', 'category_id') if getattr(before, a, None) != getattr(after, a, None)}
        if changes:
            await self.audit(after.guild, None, 'Canal alterado', {'channel': after.name, **changes}, 'log_server_channel_id')

    @commands.Cog.listener()
    async def on_message_delete(self, msg):
        if msg.guild and (not msg.author.bot):
            await self.audit(msg.guild, None, 'Mensagem excluída', {'author_id': msg.author.id, 'channel_id': msg.channel.id, 'content': clip(msg.content, 500)}, 'log_server_channel_id', GOLD)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild and before.content != after.content and (not before.author.bot):
            await self.audit(before.guild, before.author.id, 'Mensagem editada', {'channel_id': before.channel.id, 'before': clip(before.content, 400), 'after': clip(after.content, 400)}, 'log_server_channel_id')

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        cfg = await self.config(member.guild.id)
        trigger_id = cfg.get('temp_voice_trigger_id')
        if after.channel and trigger_id and (after.channel.id == trigger_id) and (before.channel is None or before.channel.id != trigger_id):
            category = member.guild.get_channel(cfg.get('temp_voice_category_id')) if cfg.get('temp_voice_category_id') else after.channel.category
            name = f'{member.display_name} • Sala'[:90]
            try:
                ch = await member.guild.create_voice_channel(name, category=category, reason=f'Nexus temp voice owner {member.id}')
                await self.pool.execute('INSERT INTO sistemas_temp_voice(channel_id,guild_id,owner_id) VALUES($1,$2,$3) ON CONFLICT(channel_id) DO NOTHING', ch.id, member.guild.id, member.id)
                await member.move_to(ch)
                await self.audit(member.guild, member.id, 'Sala temporária criada', {'channel_id': ch.id, 'owner_id': member.id}, 'log_server_channel_id')
            except discord.HTTPException:
                log.exception('Temp voice create failed')
        if before.channel and before.channel.id != (trigger_id or -1):
            row = await self.pool.fetchrow('SELECT owner_id FROM sistemas_temp_voice WHERE channel_id=$1', before.channel.id)
            if row and (not before.channel.members):
                try:
                    await before.channel.delete(reason='Nexus temporary voice empty cleanup')
                    await self.pool.execute('DELETE FROM sistemas_temp_voice WHERE channel_id=$1', before.channel.id)
                except discord.HTTPException:
                    log.exception('Temp voice cleanup failed')

    @app_commands.command(name='temp_voice_config', description='Configurar canal gatilho e categoria para salas temporárias.')
    @app_commands.checks.has_permissions(administrator=True)
    async def temp_voice_config(self, inter, trigger: discord.VoiceChannel, category: Optional[discord.CategoryChannel]=None):
        await self.setcfg(inter.guild.id, 'temp_voice_trigger_id', trigger.id)
        await self.setcfg(inter.guild.id, 'temp_voice_category_id', category.id if category else trigger.category_id)
        await reply(inter, f'Canal gatilho {trigger.mention} configurado. Salas vazias são excluídas automaticamente.')

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.guild:
            await self.audit(ctx.guild, ctx.author.id, 'Comando prefixo', {'command': ctx.command.qualified_name if ctx.command else '?', 'channel_id': ctx.channel.id}, 'log_internal_channel_id')

    @commands.Cog.listener()
    async def on_app_command_completion(self, inter, command):
        if inter.guild:
            await self.audit(inter.guild, inter.user.id, 'Comando slash', {'command': command.qualified_name, 'channel_id': inter.channel_id}, 'log_internal_channel_id')

    @commands.Cog.listener()
    async def on_app_command_error(self, inter, error):
        log.error('Application command failure', exc_info=error)
        try:
            await reply(inter, 'Falha ao executar. Erro técnico registrado, sem expor dados sensíveis.')
        except Exception:
            pass
        if inter.guild:
            await self.audit(inter.guild, inter.user.id, 'Erro de comando', {'command': getattr(inter.command, 'name', '?'), 'error_type': type(error).__name__}, 'log_internal_channel_id', RED)

class NexusPublicPanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Ajuda & Comandos', style=discord.ButtonStyle.primary, custom_id='nexus:public:help', emoji='📘')
    async def help(self, i, b):
        await reply(i, em=embed('NEXUS • AJUDA', 'Prefixo `.`, slash commands disponíveis. `.help` exibe comandos. Economia: `.wallet`, `.daily`, `.work`, `.pay ID valor`. Staff: `.mod`, `.logs`, `.quarentena ID motivo`, `.liberar ID motivo`.'))

    @discord.ui.button(label='Status', style=discord.ButtonStyle.secondary, custom_id='nexus:public:status', emoji='📡')
    async def status(self, i, b):
        cog = i.client.get_cog('Systems')
        await cog.status_cmd.callback(cog, i)

    @discord.ui.button(label='Denunciar', style=discord.ButtonStyle.danger, custom_id='nexus:public:report', emoji='🛡️')
    async def report(self, i, b):
        await i.response.send_modal(QuickReportModal())

    @discord.ui.button(label='Sugestão', style=discord.ButtonStyle.secondary, custom_id='nexus:public:suggest', emoji='💡')
    async def suggest(self, i, b):
        await i.response.send_modal(QuickSuggestionModal())

    @discord.ui.button(label='Apelação', style=discord.ButtonStyle.secondary, custom_id='nexus:public:appeal', emoji='📨')
    async def appeal(self, i, b):
        await i.response.send_modal(QuickAppealModal())

class QuickSuggestionModal(discord.ui.Modal, title='Nexus • Sugestão'):
    content = discord.ui.TextInput(label='Sua sugestão', style=discord.TextStyle.paragraph, min_length=10, max_length=1800)

    async def on_submit(self, i):
        await i.client.get_cog('Systems').suggest_slash.callback(i.client.get_cog('Systems'), i, self.content.value)

class QuickAppealModal(discord.ui.Modal, title='Nexus • Apelação'):
    case_id = discord.ui.TextInput(label='Número do caso', min_length=1, max_length=12)
    explanation = discord.ui.TextInput(label='Explique por que pede revisão', style=discord.TextStyle.paragraph, min_length=10, max_length=1500)
    evidence = discord.ui.TextInput(label='URL de prova (opcional)', required=False, max_length=500)

    async def on_submit(self, i):
        if not self.case_id.value.isdigit():
            return await reply(i, 'Número de caso inválido.')
        await i.client.get_cog('Systems').appeal_slash.callback(i.client.get_cog('Systems'), i, int(self.case_id.value), self.explanation.value, self.evidence.value or '')

class QuickReportModal(discord.ui.Modal, title='Nexus • Denúncia'):
    target = discord.ui.TextInput(label='ID do membro', min_length=17, max_length=20)
    reason = discord.ui.TextInput(label='Relato', style=discord.TextStyle.paragraph, min_length=10, max_length=1500)
    evidence = discord.ui.TextInput(label='Provas (URL opcional)', required=False, max_length=500)

    async def on_submit(self, i):
        cog = i.client.get_cog('Systems')
        if not self.target.value.isdigit():
            return await reply(i, 'ID inválido.')
        await cog.report_slash.callback(cog, i, await i.client.fetch_user(int(self.target.value)), self.reason.value, self.evidence.value or None)

class NexusRemotePanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    async def check(self, i):
        ids = set((int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS', '').split(',') if x.strip().isdigit()))
        if i.user.id not in ids:
            await reply(i, 'Acesso remoto negado.')
            return False
        return True

    @discord.ui.button(label='Listar servidores', style=discord.ButtonStyle.primary, custom_id='nexus:remote:guilds')
    async def guilds(self, i, b):
        if not await self.check(i):
            return
        rows = [f"**{g.name}** • `{g.id}` • {g.member_count or '?'} membros" for g in i.client.guilds]
        await reply(i, em=embed('NEXUS • SERVIDORES', '\n'.join(rows[:40]) or 'Nenhum servidor.'))

    @discord.ui.button(label='Enviar mensagem', style=discord.ButtonStyle.secondary, custom_id='nexus:remote:send')
    async def send(self, i, b):
        if not await self.check(i):
            return
        await i.response.send_modal(RemoteMessageModal())

    @discord.ui.button(label='Monitoramento', style=discord.ButtonStyle.success, custom_id='nexus:remote:monitor')
    async def monitor(self, i, b):
        if not await self.check(i):
            return
        cog = i.client.get_cog('Systems')
        await cog.status_cmd.callback(cog, i)

class RemoteMessageModal(discord.ui.Modal, title='Remote Ops • Envio controlado'):
    guild_id = discord.ui.TextInput(label='ID do servidor', min_length=17, max_length=20)
    channel_id = discord.ui.TextInput(label='ID do canal', min_length=17, max_length=20)
    content = discord.ui.TextInput(label='Mensagem', style=discord.TextStyle.paragraph, max_length=1900)

    async def on_submit(self, i):
        ids = set((int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS', '').split(',') if x.strip()))
        if i.user.id not in ids:
            return await reply(i, 'Acesso remoto negado.')
        if not self.guild_id.value.isdigit() or not self.channel_id.value.isdigit():
            return await reply(i, 'IDs inválidos.')
        g = i.client.get_guild(int(self.guild_id.value))
        ch = g.get_channel(int(self.channel_id.value)) if g else None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return await reply(i, 'Canal não encontrado ou tipo não permitido.')
        try:
            await ch.send(self.content.value, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            return await reply(i, f'Falha de envio: {clip(e, 200)}')
        cog = i.client.get_cog('Systems')
        await cog.audit(g, i.user.id, 'Remote Ops • mensagem enviada', {'channel_id': ch.id, 'content_length': len(self.content.value)}, 'log_internal_channel_id')
        await reply(i, 'Mensagem enviada e auditada.')

class RequestDecisionView(discord.ui.View):

    def __init__(self, rid):
        super().__init__(timeout=None)
        self.rid = rid

    async def interaction_check(self, i):
        cog = i.client.get_cog('Systems')
        cfg = await cog.config(i.guild.id)
        if not staff(i.user, cfg):
            await reply(i, 'Somente staff configurada.')
            return False
        return True

    @discord.ui.button(label='Aprovar', style=discord.ButtonStyle.success, custom_id='nexus:req:approve')
    async def approve(self, i, b):
        await i.client.get_cog('Systems').decision(i, self.rid, 'approved')

    @discord.ui.button(label='Recusar', style=discord.ButtonStyle.danger, custom_id='nexus:req:deny')
    async def deny(self, i, b):
        await i.client.get_cog('Systems').decision(i, self.rid, 'denied')

class AppealDecisionView(discord.ui.View):

    def __init__(self, aid):
        super().__init__(timeout=None)
        self.aid = aid

    async def interaction_check(self, i):
        cfg = await i.client.get_cog('Systems').config(i.guild.id)
        if not staff(i.user, cfg):
            await reply(i, 'Somente staff.')
            return False
        return True

    @discord.ui.button(label='Aceitar', style=discord.ButtonStyle.success, custom_id='nexus:appeal:approve')
    async def accept(self, i, b):
        await i.client.get_cog('Systems').appeal_decision(i, self.aid, 'approved', 'Recurso aceito')

    @discord.ui.button(label='Recusar', style=discord.ButtonStyle.danger, custom_id='nexus:appeal:deny')
    async def reject(self, i, b):
        await i.client.get_cog('Systems').appeal_decision(i, self.aid, 'denied', 'Recurso recusado')

async def setup(bot):
    main = sys.modules.get('__main__') or sys.modules.get('main')
    pool = getattr(main, 'db_pool', None) if main else None
    if pool is None or not hasattr(pool, 'acquire'):
        raise RuntimeError('Pool asyncpg db_pool do main.py não foi localizado antes do load de sistemas.')
    current = bot.command_prefix
    if isinstance(current, str):
        bot.command_prefix = commands.when_mentioned_or('.', current)
    elif isinstance(current, (tuple, list)):
        bot.command_prefix = commands.when_mentioned_or('.', *current)
    elif callable(current):
        old = current

        async def prefixmix(b, m):
            got = old(b, m)
            got = await got if hasattr(got, '__await__') else got
            return list(dict.fromkeys(['.', *([got] if isinstance(got, str) else got or [])]))
        bot.command_prefix = prefixmix
    await bot.add_cog(Systems(bot, pool))
    await bot.add_cog(NexusExtended(bot, pool))
    await bot.add_cog(NexusOperations(bot, pool))
    await bot.add_cog(NexusCommunity(bot, pool))
    await bot.add_cog(NexusInteractions(bot, pool))
    await bot.add_cog(NexusVirtualEconomy(bot, pool))
    await bot.add_cog(NexusSecurity(bot, pool))
    await bot.add_cog(NexusWorkflow(bot, pool))
    await bot.add_cog(NexusAdminTools(bot, pool))
    await bot.add_cog(NexusAdvanced(bot, pool))
    await bot.add_cog(NexusGuildTools(bot, pool))
    await bot.add_cog(NexusUtilities(bot, pool))
    await bot.add_cog(NexusStaffMetrics(bot, pool))
    await bot.add_cog(NexusRecurringAnnouncements(bot, pool))
    await bot.add_cog(NexusSuggestionVotes(bot, pool))
    await bot.add_cog(NexusModerationAnalytics(bot, pool))
    await bot.add_cog(NexusModerationTemplates(bot, pool))

class NexusExtended(commands.Cog):
    group_1 = app_commands.Group(name='ext_admin', description='NexusExtended commands (ext_admin)')
    group_2 = app_commands.Group(name='ext_community', description='NexusExtended commands (ext_community)')
    group_3 = app_commands.Group(name='ext_economy', description='NexusExtended commands (ext_economy)')
    'Additional community, moderation, economy and operations commands.'

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def _cfg(self, guild_id):
        cog = self.bot.get_cog('Systems')
        return await cog.config(guild_id)

    async def _staff_check(self, interaction):
        cfg = await self._cfg(interaction.guild.id)
        if not staff(interaction.user, cfg):
            await reply(interaction, '⛔ Este comando é exclusivo da equipe configurada.')
            return False
        return True

    async def _audit(self, guild, actor, action, details, key='log_internal_channel_id', color=PURPLE):
        core = self.bot.get_cog('Systems')
        await core.audit(guild, actor, action, details, key, color)

    @group_1.command(name='servidor_info', description='Exibe informações completas do servidor.')
    async def server_info(self, inter):
        g = inter.guild
        e = embed(f'🏰 {g.name} • Informações', color=PURPLE)
        e.set_thumbnail(url=g.icon.url if g.icon else VISUALS['shield'])
        owner = g.owner.mention if g.owner else f'<@{g.owner_id}>'
        e.add_field(name='👑 Proprietário', value=owner, inline=True)
        e.add_field(name='🆔 ID', value=str(g.id), inline=True)
        e.add_field(name='👥 Membros', value=f'{g.member_count:,}', inline=True)
        e.add_field(name='📅 Criado', value=f'<t:{int(g.created_at.timestamp())}:F>', inline=False)
        e.add_field(name='💬 Canais', value=f'{len(g.text_channels)} texto • {len(g.voice_channels)} voz', inline=True)
        e.add_field(name='🎭 Cargos', value=str(len(g.roles)), inline=True)
        e.add_field(name='🚀 Boosts', value=f'{g.premium_subscription_count or 0} • nível {g.premium_tier}', inline=True)
        e.add_field(name='🔐 Verificação', value=str(g.verification_level).replace('_', ' ').title(), inline=True)
        e.add_field(name='🌍 Região', value='Automática (Discord)', inline=True)
        if g.description:
            e.add_field(name='📝 Descrição', value=clip(g.description, 800), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='usuario_info', description='Mostra informações de um membro.')
    async def user_info(self, inter, membro: Optional[discord.Member]=None):
        m = membro or inter.user
        e = embed(f'👤 Perfil • {m.display_name}')
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='ID', value=str(m.id), inline=True)
        e.add_field(name='Conta criada', value=f'<t:{int(m.created_at.timestamp())}:R>', inline=True)
        e.add_field(name='Entrou no servidor', value=f'<t:{int(m.joined_at.timestamp())}:R>' if m.joined_at else 'Desconhecido', inline=True)
        e.add_field(name='Cargo mais alto', value=m.top_role.mention, inline=True)
        roles = [r.mention for r in reversed(m.roles[1:])]
        e.add_field(name=f'Cargos ({len(roles)})', value=clip(' '.join(roles) or 'Nenhum', 1000), inline=False)
        e.add_field(name='Permissões básicas', value=', '.join((p for p, ok in [('Administrador', m.guild_permissions.administrator), ('Gerenciar servidor', m.guild_permissions.manage_guild), ('Gerenciar mensagens', m.guild_permissions.manage_messages), ('Banir', m.guild_permissions.ban_members), ('Expulsar', m.guild_permissions.kick_members)] if ok)) or 'Nenhuma permissão especial', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='avatar', description='Exibe o avatar em tamanho grande.')
    async def avatar_cmd(self, inter, usuario: Optional[discord.User]=None):
        u = usuario or inter.user
        e = embed(f'🖼️ Avatar • {u.display_name}')
        e.set_image(url=u.display_avatar.with_size(1024).url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='banner', description='Exibe o banner de um usuário, quando disponível.')
    async def banner_cmd(self, inter, usuario: Optional[discord.User]=None):
        u = usuario or inter.user
        full = await self.bot.fetch_user(u.id)
        if not full.banner:
            return await reply(inter, 'Este usuário não possui banner público disponível.')
        e = embed(f'🎨 Banner • {full.name}')
        e.set_image(url=full.banner.url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='poll', description='Cria uma enquete com reações de votação.')
    async def poll_cmd(self, inter, pergunta: str, opcao1: str, opcao2: str, opcao3: Optional[str]=None, opcao4: Optional[str]=None):
        choices = [opcao1, opcao2] + ([opcao3] if opcao3 else []) + ([opcao4] if opcao4 else [])
        if any((len(x) > 100 for x in choices)):
            return await reply(inter, 'Cada opção deve ter no máximo 100 caracteres.')
        e = embed(f'📊 ENQUETE • {clip(pergunta, 220)}', 'Vote clicando na reação correspondente. A votação fica aberta na mensagem.')
        marks = ['1️⃣', '2️⃣', '3️⃣', '4️⃣']
        for i, option in enumerate(choices):
            e.add_field(name=f'{marks[i]} Opção {i + 1}', value=option, inline=False)
        await inter.response.send_message(embed=e)
        m = await inter.original_response()
        for mark in marks[:len(choices)]:
            try:
                await m.add_reaction(mark)
            except discord.HTTPException:
                break

    @group_1.command(name='limpar', description='Limpa mensagens recentes do canal (staff).')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_cmd(self, inter, quantidade: app_commands.Range[int, 1, 100], membro: Optional[discord.Member]=None):
        await inter.response.defer(ephemeral=True)

        def check(m):
            return membro is None or m.author.id == membro.id
        deleted = await inter.channel.purge(limit=quantidade, check=check, reason=f'Limpeza solicitada por {inter.user.id}')
        await inter.followup.send(f'🧹 **{len(deleted)}** mensagens removidas.', ephemeral=True)
        await self._audit(inter.guild, inter.user.id, 'Limpeza de mensagens', {'count': len(deleted), 'channel': inter.channel.id, 'filter_user': membro.id if membro else None})

    @group_1.command(name='slowmode', description='Configura o modo lento do canal atual.')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_cmd(self, inter, segundos: app_commands.Range[int, 0, 21600]):
        await inter.channel.edit(slowmode_delay=segundos, reason=f'Slowmode por {inter.user.id}')
        await reply(inter, f'🐢 Modo lento configurado para **{segundos} segundos**.')
        await self._audit(inter.guild, inter.user.id, 'Slowmode alterado', {'channel': inter.channel.id, 'seconds': segundos})

    @group_1.command(name='trancar', description='Tranca o canal atual para @everyone.')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_cmd(self, inter, motivo: str='Canal trancado pela equipe'):
        ow = inter.channel.overwrites_for(inter.guild.default_role)
        ow.send_messages = False
        await inter.channel.set_permissions(inter.guild.default_role, overwrite=ow, reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f'🔒 Canal trancado. Motivo: {clip(motivo, 300)}')
        await self._audit(inter.guild, inter.user.id, 'Canal trancado', {'channel': inter.channel.id, 'reason': motivo})

    @group_1.command(name='destrancar', description='Libera envio de mensagens de @everyone no canal.')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_cmd(self, inter, motivo: str='Canal destrancado pela equipe'):
        ow = inter.channel.overwrites_for(inter.guild.default_role)
        ow.send_messages = None
        await inter.channel.set_permissions(inter.guild.default_role, overwrite=ow, reason=f'{inter.user.id}: {motivo}')
        await reply(inter, '🔓 Canal destrancado.')
        await self._audit(inter.guild, inter.user.id, 'Canal destrancado', {'channel': inter.channel.id, 'reason': motivo})

    @group_1.command(name='nick', description='Altera o apelido de um membro.')
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nick_cmd(self, inter, membro: discord.Member, apelido: Optional[str]=None):
        if membro.top_role >= inter.user.top_role and inter.user.id != inter.guild.owner_id:
            return await reply(inter, 'Não posso alterar o apelido de membro com cargo igual ou superior ao seu.')
        await membro.edit(nick=apelido, reason=f'Nick editado por {inter.user.id}')
        await reply(inter, '✏️ Apelido atualizado.')
        await self._audit(inter.guild, inter.user.id, 'Apelido alterado', {'member': membro.id, 'nickname': apelido})

    @group_1.command(name='cargo_adicionar', description='Adiciona um cargo a um membro.')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, inter, membro: discord.Member, cargo: discord.Role):
        if cargo >= inter.guild.me.top_role or cargo >= inter.user.top_role:
            return await reply(inter, 'Hierarquia de cargo impede esta operação.')
        await membro.add_roles(cargo, reason=f'Cargo concedido por {inter.user.id}')
        await reply(inter, f'✅ {cargo.mention} adicionado a {membro.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Cargo concedido', {'member': membro.id, 'role': cargo.id})

    @group_1.command(name='cargo_remover', description='Remove um cargo de um membro.')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(self, inter, membro: discord.Member, cargo: discord.Role):
        if cargo >= inter.guild.me.top_role or cargo >= inter.user.top_role:
            return await reply(inter, 'Hierarquia de cargo impede esta operação.')
        await membro.remove_roles(cargo, reason=f'Cargo removido por {inter.user.id}')
        await reply(inter, f'✅ {cargo.mention} removido de {membro.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Cargo removido', {'member': membro.id, 'role': cargo.id})

    @group_1.command(name='kick', description='Expulsa membro com motivo.')
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_cmd(self, inter, membro: discord.Member, motivo: str):
        ok, msg = hierarchy(inter.user, membro, inter.guild.me)
        if not ok:
            return await reply(inter, msg)
        await membro.kick(reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f'👢 {membro} foi expulso. Motivo: {clip(motivo, 300)}')
        await self._audit(inter.guild, inter.user.id, 'Kick', {'member': membro.id, 'reason': motivo}, 'log_punishment_channel_id', RED)

    @group_1.command(name='ban', description='Bane membro com motivo.')
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_cmd(self, inter, membro: discord.Member, motivo: str, apagar_mensagens_horas: app_commands.Range[int, 0, 168]=0):
        ok, msg = hierarchy(inter.user, membro, inter.guild.me)
        if not ok:
            return await reply(inter, msg)
        await membro.ban(reason=f'{inter.user.id}: {motivo}', delete_message_seconds=apagar_mensagens_horas * 3600)
        await reply(inter, f'🔨 {membro} banido. Motivo: {clip(motivo, 300)}')
        await self._audit(inter.guild, inter.user.id, 'Ban', {'member': membro.id, 'reason': motivo, 'delete_hours': apagar_mensagens_horas}, 'log_punishment_channel_id', RED)

    @group_1.command(name='unban', description='Desbane um ID de usuário.')
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_cmd(self, inter, user_id: str, motivo: str='Desbanimento manual'):
        if not user_id.isdigit():
            return await reply(inter, 'ID precisa conter apenas números.')
        target = discord.Object(id=int(user_id))
        try:
            await inter.guild.unban(target, reason=f'{inter.user.id}: {motivo}')
        except discord.NotFound:
            return await reply(inter, 'Este ID não está banido.')
        await reply(inter, f'♻️ ID `{user_id}` desbanido.')
        await self._audit(inter.guild, inter.user.id, 'Unban', {'user_id': user_id, 'reason': motivo}, 'log_punishment_channel_id', GREEN)

    @group_1.command(name='timeout', description='Aplica timeout por minutos.')
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_cmd(self, inter, membro: discord.Member, minutos: app_commands.Range[int, 1, 40320], motivo: str):
        ok, msg = hierarchy(inter.user, membro, inter.guild.me)
        if not ok:
            return await reply(inter, msg)
        await membro.timeout(timedelta(minutes=min(minutos, 40320)), reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f'⏳ Timeout aplicado a {membro.mention} por **{minutos} min**.')
        await self._audit(inter.guild, inter.user.id, 'Timeout', {'member': membro.id, 'minutes': minutos, 'reason': motivo}, 'log_punishment_channel_id', RED)

    @group_1.command(name='timeout_remover', description='Remove timeout de um membro.')
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_remove(self, inter, membro: discord.Member, motivo: str='Timeout removido'):
        ok, msg = hierarchy(inter.user, membro, inter.guild.me)
        if not ok:
            return await reply(inter, msg)
        await membro.timeout(None, reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f'🔓 Timeout removido de {membro.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Timeout removido', {'member': membro.id, 'reason': motivo}, 'log_punishment_channel_id', GREEN)

    @group_1.command(name='mensagem_embed', description='Publicar embed tematizado Nexus no canal selecionado.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_send(self, inter, canal: discord.TextChannel, titulo: str, descricao: str, imagem_url: Optional[str]=None):
        if imagem_url and (not url_ok(imagem_url)):
            return await reply(inter, 'A imagem precisa ser URL HTTP/HTTPS válida.')
        e = embed(clip(titulo, 256), clip(descricao, 4000), PURPLE)
        if imagem_url:
            e.set_image(url=imagem_url)
        cfg = await self._cfg(inter.guild.id)
        if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']) and (not imagem_url):
            e.set_image(url=cfg['theme_image_url'])
        await canal.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, f'📨 Embed publicada em {canal.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Embed publicada', {'channel': canal.id, 'title': titulo})

    @group_1.command(name='anuncio', description='Publica anúncio com tema Nexus.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def announcement(self, inter, canal: discord.TextChannel, titulo: str, texto: str, ping_everyone: bool=False):
        e = embed(f'📢 {clip(titulo, 220)}', clip(texto, 4000), GOLD)
        cfg = await self._cfg(inter.guild.id)
        if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
            e.set_image(url=cfg['theme_image_url'])
        await canal.send(content='@everyone' if ping_everyone else None, embed=e, allowed_mentions=discord.AllowedMentions(everyone=ping_everyone, users=False, roles=False))
        await reply(inter, f'Anúncio publicado em {canal.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Anúncio publicado', {'channel': canal.id, 'title': titulo, 'everyone': ping_everyone})

    @group_1.command(name='anuncio_agendar', description='Agenda anúncio para data/hora UTC.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def announcement_schedule(self, inter, canal: discord.TextChannel, data_iso_utc: str, mensagem: str):
        try:
            when = datetime.fromisoformat(data_iso_utc.replace('Z', '+00:00'))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when = when.astimezone(timezone.utc)
        except ValueError:
            return await reply(inter, 'Data inválida. Use ISO: `2026-12-01T20:00:00Z`.')
        if when <= datetime.now(timezone.utc):
            return await reply(inter, 'A data precisa estar no futuro.')
        aid = await self.pool.fetchval('INSERT INTO nexus_announcements(guild_id,channel_id,content,send_at,created_by) VALUES($1,$2,$3,$4,$5) RETURNING id', inter.guild.id, canal.id, mensagem, when, inter.user.id)
        await reply(inter, f'🗓️ Anúncio agendado **#{aid}** para <t:{int(when.timestamp())}:F>.')
        await self._audit(inter.guild, inter.user.id, 'Anúncio agendado', {'announcement_id': aid, 'channel': canal.id, 'send_at': when.isoformat()})

    @group_1.command(name='economia_saldo', description='Consulta saldo de um membro.')
    async def balance(self, inter, membro: Optional[discord.User]=None):
        target = membro or inter.user
        core = self.bot.get_cog('Systems')
        await inter.response.send_message(embed=await core.wallet_embed(inter.guild, target.id), ephemeral=True)

    @group_1.command(name='economia_transferir', description='Transfere moedas NXC entre usuários.')
    async def transfer(self, inter, destino: discord.User, valor: app_commands.Range[int, 1, 100000000]):
        if destino.bot or destino.id == inter.user.id:
            return await reply(inter, 'Destino inválido; bots e auto-transferências não são permitidos.')
        gid, src, dst = (inter.guild.id, inter.user.id, destino.id)
        cfg = await self._cfg(gid)
        if valor > int(cfg.get('economy_transfer_limit', 100000)):
            return await reply(inter, f"Valor excede limite de {int(cfg.get('economy_transfer_limit', 100000)):,} NXC.")
        core = self.bot.get_cog('Systems')
        await core.ensure_wallet(gid, src)
        await core.ensure_wallet(gid, dst)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock($1)', min(src, dst))
                await conn.execute('SELECT pg_advisory_xact_lock($1)', max(src, dst))
                bal = await conn.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', gid, src)
                if bal < valor:
                    return await reply(inter, 'Saldo insuficiente.')
                await conn.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2', gid, src, valor)
                await conn.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2', gid, dst, valor)
                await conn.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$3,$4,$5)', gid, src, dst, valor, 'transfer')
        await reply(inter, f'💸 Transferidos **{valor:,} NXC** para {destino.mention}.')

    @group_1.command(name='economia_add', description='Adiciona moeda virtual (staff).')
    async def economy_add(self, inter, membro: discord.User, valor: app_commands.Range[int, 1, 100000000], motivo: str):
        if not await self._staff_check(inter):
            return
        core = self.bot.get_cog('Systems')
        await core.ensure_wallet(inter.guild.id, membro.id)
        await self.pool.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id, valor)
        await self.pool.execute('INSERT INTO nexus_economy_tx(guild_id,to_user,amount,kind) VALUES($1,$2,$3,$4)', inter.guild.id, membro.id, valor, 'admin_add')
        await reply(inter, f'➕ {valor:,} NXC adicionados a {membro.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Economia: saldo adicionado', {'user': membro.id, 'amount': valor, 'reason': motivo})

    @group_1.command(name='economia_remover', description='Remove moeda virtual (staff).')
    async def economy_remove(self, inter, membro: discord.User, valor: app_commands.Range[int, 1, 100000000], motivo: str):
        if not await self._staff_check(inter):
            return
        await self.pool.execute('UPDATE nexus_wallets SET balance=GREATEST(balance-$3,0) WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id, valor)
        await self.pool.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,amount,kind) VALUES($1,$2,$3,$4)', inter.guild.id, membro.id, valor, 'admin_remove')
        await reply(inter, f'➖ Saldo de {membro.mention} ajustado.')
        await self._audit(inter.guild, inter.user.id, 'Economia: saldo removido', {'user': membro.id, 'amount': valor, 'reason': motivo})

    @group_1.command(name='loja_produto_criar', description='Cria produto na loja virtual Nexus.')
    async def product_create(self, inter, nome: str, descricao: str, preco_nxc: app_commands.Range[int, 1, 100000000], estoque: app_commands.Range[int, 0, 1000000]):
        if not await self._staff_check(inter):
            return
        pid = await self.pool.fetchval('INSERT INTO nexus_products(guild_id,name,description,price_cents,stock,category) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', inter.guild.id, clip(nome, 100), clip(descricao, 1000), preco_nxc * 100, estoque, 'NXC')
        await reply(inter, f'🛍️ Produto **#{pid}** criado. Preço: {preco_nxc:,} NXC.')
        await self._audit(inter.guild, inter.user.id, 'Loja: produto criado', {'product': pid, 'name': nome, 'price': preco_nxc, 'stock': estoque})

    @group_2.command(name='loja_produto_remover', description='Desativa produto da loja.')
    async def product_remove(self, inter, produto_id: int):
        if not await self._staff_check(inter):
            return
        res = await self.pool.execute('UPDATE nexus_products SET active=FALSE WHERE guild_id=$1 AND id=$2 AND active=TRUE', inter.guild.id, produto_id)
        await reply(inter, '🗑️ Produto desativado.' if res.endswith('1') else 'Produto não encontrado ou já desativado.')
        await self._audit(inter.guild, inter.user.id, 'Loja: produto desativado', {'product': produto_id})

    @group_2.command(name='loja_comprar', description='Compra produto da loja usando moedas virtuais.')
    async def product_buy(self, inter, produto_id: int, quantidade: app_commands.Range[int, 1, 25]=1):
        gid, uid = (inter.guild.id, inter.user.id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock($1)', uid)
                product = await conn.fetchrow('SELECT * FROM nexus_products WHERE guild_id=$1 AND id=$2 AND active=TRUE FOR UPDATE', gid, produto_id)
                if not product:
                    return await reply(inter, 'Produto não encontrado/indisponível.')
                if product['stock'] < quantidade:
                    return await reply(inter, 'Estoque insuficiente.')
                price = product['price_cents'] // 100 * quantidade
                core = self.bot.get_cog('Systems')
                await core.ensure_wallet(gid, uid)
                balance = await conn.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', gid, uid)
                if balance < price:
                    return await reply(inter, f'Saldo insuficiente. Custo: **{price:,} NXC**.')
                await conn.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2', gid, uid, price)
                await conn.execute('UPDATE nexus_products SET stock=stock-$2 WHERE guild_id=$1 AND id=$3', gid, quantidade, produto_id)
                order = await conn.fetchval('INSERT INTO nexus_orders(guild_id,user_id,product_id,qty,status,total_cents) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', gid, uid, produto_id, quantidade, 'paid_virtual', price * 100)
                await conn.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$3,$4,$5)', gid, uid, None, price, 'shop_purchase')
        await reply(inter, f"🛒 Compra **#{order}** confirmada com moeda virtual. {quantidade}x {product['name']} • **{price:,} NXC**.")
        await self._audit(inter.guild, inter.user.id, 'Loja: compra', {'order': order, 'product': produto_id, 'qty': quantidade, 'total_nxc': price})

    @group_2.command(name='loja_pedidos', description='Lista pedidos recentes da loja (staff).')
    async def orders_list(self, inter):
        if not await self._staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT o.id,o.user_id,o.product_id,o.qty,o.status,o.total_cents,o.created_at,p.name FROM nexus_orders o LEFT JOIN nexus_products p ON p.id=o.product_id WHERE o.guild_id=$1 ORDER BY o.id DESC LIMIT 15', inter.guild.id)
        e = embed('🧾 NEXUS • PEDIDOS', f'{len(rows)} pedidos recentes')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['status']}", value=f"Usuário: <@{r['user_id']}>\nProduto: {r['name'] or r['product_id']} • {r['qty']}x\nTotal virtual: {r['total_cents'] / 100:,.0f} NXC", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='staff_tarefa_criar', description='Cria tarefa para um membro da equipe.')
    async def task_create(self, inter, responsavel: discord.Member, titulo: str, detalhes: str=''):
        if not await self._staff_check(inter):
            return
        tid = await self.pool.fetchval('INSERT INTO nexus_staff_tasks(guild_id,assignee_id,creator_id,title,details) VALUES($1,$2,$3,$4,$5) RETURNING id', inter.guild.id, responsavel.id, inter.user.id, clip(titulo, 180), clip(detalhes, 1500))
        e = embed(f'📋 Tarefa de staff • #{tid}', f'**{clip(titulo, 180)}**\n{clip(detalhes, 1200)}\n\nResponsável: {responsavel.mention}\nCriada por: {inter.user.mention}')
        try:
            await responsavel.send(embed=e)
        except discord.HTTPException:
            pass
        await reply(inter, f'Tarefa **#{tid}** criada para {responsavel.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Staff: tarefa criada', {'task': tid, 'assignee': responsavel.id, 'title': titulo})

    @group_2.command(name='staff_tarefas', description='Lista tarefas da equipe (staff).')
    async def task_list(self, inter, status: str='open'):
        if not await self._staff_check(inter):
            return
        if status not in ('open', 'done', 'cancelled', 'all'):
            return await reply(inter, 'Status inválido: open/done/cancelled/all.')
        rows = await self.pool.fetch('SELECT id,assignee_id,title,details,status,due_at FROM nexus_staff_tasks WHERE guild_id=$1 AND ($2=$3 OR status=$2) ORDER BY id DESC LIMIT 25', inter.guild.id, status, 'all')
        e = embed('📋 NEXUS • TAREFAS', f'{len(rows)} tarefas')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['status']} • <@{r['assignee_id']}>", value=f"**{r['title']}**\n{clip(r['details'] or '', 300)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='staff_tarefa_concluir', description='Marca tarefa como concluída.')
    async def task_finish(self, inter, tarefa_id: int):
        row = await self.pool.fetchrow('SELECT * FROM nexus_staff_tasks WHERE guild_id=$1 AND id=$2', inter.guild.id, tarefa_id)
        if not row:
            return await reply(inter, 'Tarefa não encontrada.')
        cfg = await self._cfg(inter.guild.id)
        if inter.user.id != row['assignee_id'] and (not staff(inter.user, cfg)):
            return await reply(inter, 'Somente responsavel ou staff pode concluir.')
        await self.pool.execute("UPDATE nexus_staff_tasks SET status='done' WHERE guild_id=$1 AND id=$2", inter.guild.id, tarefa_id)
        await reply(inter, f'✅ Tarefa **#{tarefa_id}** concluída.')
        await self._audit(inter.guild, inter.user.id, 'Staff: tarefa concluída', {'task': tarefa_id})

    @group_2.command(name='evento_criar', description='Cria evento comunitário e registra no banco.')
    async def event_create(self, inter, titulo: str, descricao: str, canal: discord.TextChannel, data_iso_utc: str):
        if not await self._staff_check(inter):
            return
        try:
            when = datetime.fromisoformat(data_iso_utc.replace('Z', '+00:00'))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when = when.astimezone(timezone.utc)
        except ValueError:
            return await reply(inter, 'Data inválida. Formato ISO UTC, ex. `2026-12-10T20:00:00Z`.')
        if when <= datetime.now(timezone.utc):
            return await reply(inter, 'Data deve estar no futuro.')
        eid = await self.pool.fetchval('INSERT INTO nexus_events(guild_id,creator_id,title,description,channel_id,ends_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', inter.guild.id, inter.user.id, clip(titulo, 200), clip(descricao, 1500), canal.id, when)
        e = embed(f'🎉 EVENTO NEXUS • #{eid}', f'**{clip(titulo, 200)}**\n{clip(descricao, 2000)}\n\n📅 <t:{int(when.timestamp())}:F>\nClique em 🎉 para participar.')
        m = await canal.send(embed=e)
        await m.add_reaction('🎉')
        await reply(inter, f'Evento **#{eid}** publicado em {canal.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Evento criado', {'event': eid, 'channel': canal.id, 'title': titulo})

    @group_2.command(name='sorteio_criar', description='Cria sorteio com participantes por reação.')
    async def giveaway_create(self, inter, premio: str, canal: discord.TextChannel, minutos: app_commands.Range[int, 1, 10080], vencedores: app_commands.Range[int, 1, 20]=1):
        if not await self._staff_check(inter):
            return
        end = datetime.now(timezone.utc) + timedelta(minutes=min(minutos, 10080))
        eid = await self.pool.fetchval('INSERT INTO nexus_events(guild_id,creator_id,title,description,channel_id,ends_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', inter.guild.id, inter.user.id, f'Sorteio: {clip(premio, 150)}', f'Vencedores: {vencedores}', canal.id, end)
        e = embed(f'🎁 SORTEIO NEXUS • #{eid}', f'**Prêmio:** {clip(premio, 300)}\n**Vencedores:** {vencedores}\n**Encerra:** <t:{int(end.timestamp())}:R>\n\nReaja 🎉 para participar!')
        m = await canal.send(embed=e)
        await m.add_reaction('🎉')
        await reply(inter, f'Sorteio **#{eid}** publicado. Para realizar o sorteio no encerramento, use `/sorteio_encerrar` com o ID.')
        await self._audit(inter.guild, inter.user.id, 'Sorteio criado', {'event': eid, 'prize': premio, 'ends_at': end.isoformat()})

    @group_2.command(name='sorteio_encerrar', description='Encerra sorteio e sorteia participantes registrados por reação.')
    async def giveaway_end(self, inter, evento_id: int):
        if not await self._staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM nexus_events WHERE guild_id=$1 AND id=$2 AND status=$3', inter.guild.id, evento_id, 'open')
        if not row:
            return await reply(inter, 'Evento/sorteio aberto não encontrado.')
        ch = inter.guild.get_channel(row['channel_id'])
        if not ch:
            return await reply(inter, 'Canal do sorteio não existe mais.')
        msg = None
        async for candidate in ch.history(limit=100):
            if candidate.embeds and f'#{evento_id}' in (candidate.embeds[0].title or ''):
                msg = candidate
                break
        if not msg:
            return await reply(inter, 'Mensagem do sorteio não encontrada no histórico recente.')
        reaction = discord.utils.get(msg.reactions, emoji='🎉')
        users = []
        if reaction:
            async for u in reaction.users():
                if not u.bot:
                    users.append(u)
        import random
        winner_count = 1
        try:
            if row['description'] and 'Vencedores:' in row['description']:
                winner_count = int(row['description'].split('Vencedores:', 1)[1].strip())
        except Exception:
            pass
        random.SystemRandom().shuffle(users)
        winners = users[:winner_count]
        await self.pool.execute("UPDATE nexus_events SET status='ended' WHERE guild_id=$1 AND id=$2", inter.guild.id, evento_id)
        out = ', '.join((u.mention for u in winners)) if winners else 'Sem participantes válidos.'
        await ch.send(embed=embed('🎊 SORTEIO ENCERRADO', f'**Evento #{evento_id}**\nVencedores: {out}'))
        await reply(inter, f'Sorteio encerrado. Vencedores: {out}')
        await self._audit(inter.guild, inter.user.id, 'Sorteio encerrado', {'event': evento_id, 'winners': [u.id for u in winners]})

    @group_2.command(name='xp_config', description='Liga/desliga XP e define cooldown de mensagens.')
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_config(self, inter, ativar: bool, cooldown_segundos: app_commands.Range[int, 10, 3600]=60):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'xp_enabled', ativar)
        await core.setcfg(inter.guild.id, 'xp_cooldown', cooldown_segundos)
        await reply(inter, f"✨ XP **{('ativado' if ativar else 'desativado')}**. Cooldown: {cooldown_segundos}s.")
        await self._audit(inter.guild, inter.user.id, 'XP configurado', {'enabled': ativar, 'cooldown': cooldown_segundos})

    @group_2.command(name='economia_config', description='Configura recompensas e cooldown da economia.')
    @app_commands.checks.has_permissions(administrator=True)
    async def economy_config(self, inter, diario: app_commands.Range[int, 0, 1000000], trabalho_min: app_commands.Range[int, 0, 1000000], trabalho_max: app_commands.Range[int, 0, 1000000], cooldown_trabalho: app_commands.Range[int, 60, 86400]):
        if trabalho_max < trabalho_min:
            return await reply(inter, 'Valor máximo de trabalho precisa ser maior ou igual ao mínimo.')
        core = self.bot.get_cog('Systems')
        for key, val in [('economy_daily', diario), ('economy_work_min', trabalho_min), ('economy_work_max', trabalho_max), ('economy_cooldown', cooldown_trabalho)]:
            await core.setcfg(inter.guild.id, key, val)
        await reply(inter, '⚙️ Configuração da economia atualizada.')
        await self._audit(inter.guild, inter.user.id, 'Economia configurada', {'daily': diario, 'work_min': trabalho_min, 'work_max': trabalho_max, 'work_cooldown': cooldown_trabalho})

    @group_2.command(name='auditoria_buscar', description='Pesquisa registros da auditoria por texto (staff).')
    async def audit_search(self, inter, termo: str, limite: app_commands.Range[int, 1, 20]=10):
        if not await self._staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT id,actor_id,action,details,created_at FROM sistemas_audit WHERE guild_id=$1 AND (action ILIKE $2 OR details::text ILIKE $2) ORDER BY id DESC LIMIT $3', inter.guild.id, f'%{termo}%', limite)
        e = embed('🔎 NEXUS • BUSCA DE AUDITORIA', f'{len(rows)} resultados para `{clip(termo, 80)}`')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['action']}", value=f"Autor: <@{r['actor_id'] or 0}>\n{clip(r['details'], 600)}\n<t:{int(r['created_at'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='backup_listar', description='Lista backups salvos do servidor (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_list(self, inter):
        rows = await self.pool.fetch('SELECT id,created_at FROM sistemas_backups WHERE guild_id=$1 ORDER BY id DESC LIMIT 10', inter.guild.id)
        e = embed('🗄️ NEXUS • BACKUPS', f'{len(rows)} backups recentes')
        for r in rows:
            e.add_field(name=f"Backup #{r['id']}", value=f"<t:{int(r['created_at'].timestamp())}:F>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='config_boasvindas', description='Configura boas-vindas e cargo automático.')
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_config(self, inter, canal: discord.TextChannel, mensagem: str, autorole: Optional[discord.Role]=None):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'welcome_channel_id', canal.id)
        await core.setcfg(inter.guild.id, 'welcome_message', clip(mensagem, 1500))
        await core.setcfg(inter.guild.id, 'autorole_id', autorole.id if autorole else None)
        await reply(inter, '👋 Boas-vindas configuradas. Variáveis disponíveis: `{member}` e `{server}`.')
        await self._audit(inter.guild, inter.user.id, 'Boas-vindas configuradas', {'channel': canal.id, 'autorole': autorole.id if autorole else None})

    @group_2.command(name='config_tema', description='Define URL de imagem temática para embeds Nexus.')
    @app_commands.checks.has_permissions(administrator=True)
    async def theme_config(self, inter, url: str):
        if not url_ok(url):
            return await reply(inter, 'URL inválida; use HTTP ou HTTPS.')
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'theme_image_url', url)
        await reply(inter, '🎨 Imagem temática atualizada. Ela será usada nos painéis e embeds que suportam imagem.')
        await self._audit(inter.guild, inter.user.id, 'Tema visual atualizado', {'url': url})

    @group_2.command(name='config_autorole', description='Configura cargo automático de novos membros.')
    @app_commands.checks.has_permissions(administrator=True)
    async def autorole_config(self, inter, cargo: Optional[discord.Role]=None):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'autorole_id', cargo.id if cargo else None)
        await reply(inter, f"🎭 Autorole: {(cargo.mention if cargo else 'desativado')}.")

    @group_2.command(name='config_staff', description='Adiciona ou remove cargo de staff reconhecido pelo Nexus.')
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_role_config(self, inter, cargo: discord.Role, adicionar: bool=True):
        core = self.bot.get_cog('Systems')
        cfg = await core.config(inter.guild.id)
        roles = set(cfg.get('staff_role_ids') or [])
        if adicionar:
            roles.add(cargo.id)
        else:
            roles.discard(cargo.id)
        await core.setcfg(inter.guild.id, 'staff_role_ids', sorted(roles))
        await reply(inter, f"🛡️ Cargo {cargo.mention} {('incluído' if adicionar else 'removido')} da lista de staff.")
        await self._audit(inter.guild, inter.user.id, 'Configuração de staff', {'role': cargo.id, 'added': adicionar})

    @group_2.command(name='config_canais', description='Configura canal para denúncias, sugestões e recrutamento.')
    @app_commands.checks.has_permissions(administrator=True)
    async def channel_config(self, inter, canal_denuncias: Optional[discord.TextChannel]=None, canal_sugestoes: Optional[discord.TextChannel]=None, canal_recrutamento: Optional[discord.TextChannel]=None):
        core = self.bot.get_cog('Systems')
        for key, ch in [('report_channel_id', canal_denuncias), ('suggestion_channel_id', canal_sugestoes), ('recruitment_channel_id', canal_recrutamento)]:
            if ch:
                await core.setcfg(inter.guild.id, key, ch.id)
        await reply(inter, '📌 Canais configurados. Campos omitidos mantêm o valor atual.')
        await self._audit(inter.guild, inter.user.id, 'Canais Nexus configurados', {'reports': canal_denuncias.id if canal_denuncias else None, 'suggestions': canal_sugestoes.id if canal_sugestoes else None, 'recruitment': canal_recrutamento.id if canal_recrutamento else None})

    @group_2.command(name='recrutamento', description='Publica painel de recrutamento da equipe.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def recruitment(self, inter, canal: discord.TextChannel, titulo: str, descricao: str):
        cfg = await self._cfg(inter.guild.id)
        e = embed(f'🛡️ RECRUTAMENTO NEXUS • {clip(titulo, 200)}', clip(descricao, 3500))
        e.add_field(name='📨 Como participar', value='Entre em contato com a equipe ou envie sua candidatura no canal configurado.', inline=False)
        if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
            e.set_image(url=cfg['theme_image_url'])
        await canal.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, '📣 Recrutamento publicado.')
        await self._audit(inter.guild, inter.user.id, 'Recrutamento publicado', {'channel': canal.id, 'title': titulo})

    @group_2.command(name='membro_destaque', description='Dá destaque comunitário a um membro em embed.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def member_spotlight(self, inter, membro: discord.Member, motivo: str, canal: Optional[discord.TextChannel]=None):
        target = canal or inter.channel
        e = embed('🌟 NEXUS • MEMBRO DESTAQUE', f'{membro.mention}\n\n**Reconhecimento:** {clip(motivo, 1200)}')
        e.set_thumbnail(url=membro.display_avatar.url)
        await target.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, 'Destaque publicado.')
        await self._audit(inter.guild, inter.user.id, 'Membro destaque', {'member': membro.id, 'reason': motivo, 'channel': target.id})

    @group_2.command(name='mensagem_pin', description='Fixar mensagem por ID no canal atual.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def pin_cmd(self, inter, mensagem_id: str):
        if not mensagem_id.isdigit():
            return await reply(inter, 'ID inválido.')
        try:
            m = await inter.channel.fetch_message(int(mensagem_id))
        except discord.NotFound:
            return await reply(inter, 'Mensagem não encontrada neste canal.')
        await m.pin(reason=f'Fixada por {inter.user.id}')
        await reply(inter, '📌 Mensagem fixada.')
        await self._audit(inter.guild, inter.user.id, 'Mensagem fixada', {'message': m.id, 'channel': inter.channel.id})

    @group_2.command(name='mensagem_unpin', description='Desfixar mensagem por ID no canal atual.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unpin_cmd(self, inter, mensagem_id: str):
        if not mensagem_id.isdigit():
            return await reply(inter, 'ID inválido.')
        try:
            m = await inter.channel.fetch_message(int(mensagem_id))
        except discord.NotFound:
            return await reply(inter, 'Mensagem não encontrada neste canal.')
        await m.unpin(reason=f'Desfixada por {inter.user.id}')
        await reply(inter, '📍 Mensagem desfixada.')
        await self._audit(inter.guild, inter.user.id, 'Mensagem desfixada', {'message': m.id, 'channel': inter.channel.id})

    @group_2.command(name='sugestoes_status', description='Lista sugestões pendentes (staff).')
    async def suggestions_status(self, inter):
        if not await self._staff_check(inter):
            return
        rows = await self.pool.fetch("SELECT id,user_id,content,status,created_at FROM sistemas_suggestions WHERE guild_id=$1 AND status='pending' ORDER BY id DESC LIMIT 20", inter.guild.id)
        e = embed('💡 NEXUS • SUGESTÕES PENDENTES', f'{len(rows)} sugestões')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <@{r['user_id']}>", value=clip(r['content'], 700), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='sugestao_decidir', description='Marca sugestão como aceita ou recusada.')
    async def suggestion_decide(self, inter, sugestao_id: int, decisao: str, justificativa: str=''):
        if not await self._staff_check(inter):
            return
        decisao = decisao.lower()
        if decisao not in ('accepted', 'denied', 'implementing'):
            return await reply(inter, 'Use accepted, denied ou implementing.')
        row = await self.pool.fetchrow('SELECT * FROM sistemas_suggestions WHERE guild_id=$1 AND id=$2', inter.guild.id, sugestao_id)
        if not row:
            return await reply(inter, 'Sugestão não encontrada.')
        await self.pool.execute('UPDATE sistemas_suggestions SET status=$3 WHERE guild_id=$1 AND id=$2', inter.guild.id, sugestao_id, decisao)
        try:
            user = await self.bot.fetch_user(row['user_id'])
            await user.send(embed=embed('💡 Resultado da sugestão', f'Sua sugestão **#{sugestao_id}** foi marcada como **{decisao}**.\n{clip(justificativa, 500)}'))
        except discord.HTTPException:
            pass
        await reply(inter, 'Status da sugestão atualizado.')
        await self._audit(inter.guild, inter.user.id, 'Sugestão decidida', {'suggestion': sugestao_id, 'status': decisao, 'reason': justificativa})

    @group_2.command(name='quarentena_status', description='Consulta status da quarentena de usuário.')
    async def quarantine_status(self, inter, usuario: discord.User):
        if not await self._staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM nexus_quarantine WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 1', inter.guild.id, usuario.id)
        if not row:
            return await reply(inter, 'Nenhum registro de quarentena encontrado.')
        expires_text = f"<t:{int(row['expires_at'].timestamp())}:F>" if row['expires_at'] else 'sem prazo'
        status_text = 'ativa' if row['active'] else 'inativa'
        e = embed('🔐 NEXUS • QUARENTENA', f"Usuário: {usuario.mention}\nStatus: **{status_text}**\nMotivo: {clip(row['reason'], 700)}\nAplicada: <t:{int(row['created_at'].timestamp())}:F>\nExpira: {expires_text}")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='punicoes_exportar', description='Exporta histórico recente de punições como CSV em anexo.')
    async def export_cases(self, inter, limite: app_commands.Range[int, 1, 100]=50):
        if not await self._staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT id,user_id,moderator_id,action,reason,created_at,expires_at,active FROM sistemas_cases WHERE guild_id=$1 ORDER BY id DESC LIMIT $2', inter.guild.id, limite)
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['case_id', 'user_id', 'moderator_id', 'action', 'reason', 'created_at', 'expires_at', 'active'])
        for r in rows:
            writer.writerow([r['id'], r['user_id'], r['moderator_id'], r['action'], r['reason'], r['created_at'].isoformat(), r['expires_at'].isoformat() if r['expires_at'] else '', r['active']])
        file = discord.File(io.BytesIO(buf.getvalue().encode('utf-8-sig')), filename=f'nexus_cases_{inter.guild.id}.csv')
        await inter.response.send_message(content=f'📁 Exportados **{len(rows)}** registros.', file=file, ephemeral=True)

    @group_3.command(name='config_protecao_avancada', description='Configura limites de spam, menções e lista de palavras.')
    @app_commands.checks.has_permissions(administrator=True)
    async def protection_advanced(self, inter, limite_spam: app_commands.Range[int, 3, 20]=5, janela_segundos: app_commands.Range[int, 2, 60]=8, limite_mencoes: app_commands.Range[int, 2, 20]=5, palavras: str=''):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'spam_count', limite_spam)
        await core.setcfg(inter.guild.id, 'spam_window', janela_segundos)
        await core.setcfg(inter.guild.id, 'max_mentions', limite_mencoes)
        clean = [x.strip().lower() for x in palavras.split(',') if x.strip()][:100]
        await core.setcfg(inter.guild.id, 'filter_words', clean)
        await reply(inter, '🛡️ Limites do AutoMod atualizados. A filtragem de palavras fica ativa independentemente dos toggles de links/spam.')
        await self._audit(inter.guild, inter.user.id, 'AutoMod avançado configurado', {'spam_count': limite_spam, 'window': janela_segundos, 'mentions': limite_mencoes, 'words_count': len(clean)})

    @group_3.command(name='painel_publicar', description='Publica o painel de acesso Nexus no canal escolhido.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def publish_panel(self, inter, canal: discord.TextChannel):
        core = self.bot.get_cog('Systems')
        await core.send_public_panel(canal, inter.user)
        await reply(inter, f'🎛️ Painel Nexus publicado em {canal.mention}.')
        await self._audit(inter.guild, inter.user.id, 'Painel público publicado', {'channel': canal.id})

    @group_3.command(name='bot_info', description='Informações técnicas do bot e latência.')
    async def bot_info(self, inter):
        e = embed('🤖 NEXUS • BOT INFO', f'**Nome:** {self.bot.user}\n**ID:** {self.bot.user.id}\n**Latência:** {self.bot.latency * 1000:.0f} ms\n**Servidores:** {len(self.bot.guilds)}\n**Usuários aproximados:** {sum((g.member_count or 0 for g in self.bot.guilds)):,}\n**Comandos slash:** {len(self.bot.tree.get_commands())}\n**Python:** {sys.version.split()[0]}')
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='comandos', description='Lista comandos e categorias do Nexus.')
    async def commands_list(self, inter):
        e = embed('📚 NEXUS • CENTRAL DE COMANDOS', 'Comandos disponíveis no bot. Alguns comandos requerem permissões administrativas ou staff.')
        e.add_field(name='🌐 Comunidade', value='/nexus • /servidor_info • /usuario_info • /avatar • /banner • /poll • /bot_info', inline=False)
        e.add_field(name='🛡️ Moderação', value='/punir • /kick • /ban • /unban • /timeout • /timeout_remover • /limpar • /slowmode • /trancar • /destrancar • /nick • /cargo_adicionar • /cargo_remover', inline=False)
        e.add_field(name='💰 Economia', value='/economia_saldo • /economia_transferir • /daily • /work • /loja • /loja_produto_criar • /loja_comprar • /economia_add • /economia_remover', inline=False)
        e.add_field(name='🎉 Comunidade', value='/sugerir • /sugestoes_status • /sugestao_decidir • /denunciar • /ranking_xp • /evento_criar • /sorteio_criar • /sorteio_encerrar • /membro_destaque', inline=False)
        e.add_field(name='👥 Equipe', value='/staff_tarefa_criar • /staff_tarefas • /staff_tarefa_concluir • /recrutamento • /solicitar_punicao • /apelar_punicao • /historico_punicoes • /auditoria_buscar', inline=False)
        e.add_field(name='⚙️ Configuração', value='/nexus_config • /nexus_config_logs • /config_boasvindas • /config_autorole • /config_staff • /config_canais • /config_tema • /automod_config • /config_protecao • /config_protecao_avancada • /xp_config • /economia_config • /temp_voice_config', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='daily', description='Resgata recompensa diária da economia virtual.')
    async def daily_slash(self, inter):
        core = self.bot.get_cog('Systems')
        success = await core.daily(inter.guild, inter.user)
        await reply(inter, '📆 Recompensa diária creditada!' if success else 'Você já recebeu a recompensa de hoje.')

    @group_3.command(name='work', description='Trabalha e recebe moedas virtuais (cooldown configurado).')
    async def work_slash(self, inter):
        core = self.bot.get_cog('Systems')
        success = await core.work(inter.guild, inter.user)
        await reply(inter, '🧰 Trabalho concluído e moedas creditadas!' if success else 'Você ainda está no cooldown de trabalho.')

    @group_3.command(name='loja', description='Exibe catálogo da loja virtual NXC.')
    async def shop_slash(self, inter):
        rows = await self.pool.fetch('SELECT id,name,description,price_cents,stock FROM nexus_products WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 25', inter.guild.id)
        e = embed('🛍️ NEXUS • LOJA', f'{len(rows)} produtos disponíveis. Use `/loja_comprar` para compras usando saldo NXC.')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['name']} • {r['price_cents'] // 100:,} NXC", value=f"{clip(r['description'], 240)}\nEstoque: {r['stock']}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='rank', description='Exibe ranking XP dos membros.')
    async def rank_slash(self, inter):
        rows = await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10', inter.guild.id)
        e = embed('✨ NEXUS • RANKING XP', 'Top 10 membros')
        for idx, r in enumerate(rows, 1):
            e.add_field(name=f"{idx}. <@{r['user_id']}>", value=f"{r['xp']:,} XP • nível {r['level']}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='nexus_health', description='Diagnóstico rápido do módulo e tabelas principais (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def health(self, inter):
        tests = []
        for label, query in [('Config', 'SELECT 1 FROM sistemas_config LIMIT 1'), ('Auditoria', 'SELECT 1 FROM sistemas_audit LIMIT 1'), ('Economia', 'SELECT 1 FROM nexus_wallets LIMIT 1'), ('Quarentena', 'SELECT 1 FROM nexus_quarantine LIMIT 1'), ('Loja', 'SELECT 1 FROM nexus_products LIMIT 1')]:
            try:
                await self.pool.fetchval(query)
                tests.append(f'✅ {label}')
            except Exception as exc:
                tests.append(f'❌ {label}: {type(exc).__name__}')
        e = embed('🩺 NEXUS • HEALTH CHECK', '\n'.join(tests))
        await inter.response.send_message(embed=e, ephemeral=True)

async def _load_extended(bot, pool):
    if bot.get_cog('NexusExtended') is None:
        await bot.add_cog(NexusExtended(bot, pool))

class NexusOperations(commands.Cog):
    group_1 = app_commands.Group(name='ops', description='NexusOperations commands (ops)')
    group_2 = app_commands.Group(name='ops_tools', description='NexusOperations commands (ops_tools)')
    group_3 = app_commands.Group(name='ops_config', description='NexusOperations commands (ops_config)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    async def allowed_staff(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Somente equipe autorizada.')
        return False

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        await self.bot.wait_until_ready()
        rows = await self.pool.fetch('SELECT id,user_id,channel_id,message,due_at FROM nexus_reminders WHERE sent=FALSE AND due_at<=NOW() ORDER BY due_at LIMIT 50')
        for r in rows:
            changed = await self.pool.execute('UPDATE nexus_reminders SET sent=TRUE WHERE id=$1 AND sent=FALSE', r['id'])
            if not changed.endswith('1'):
                continue
            user = self.bot.get_user(r['user_id'])
            if user is None:
                try:
                    user = await self.bot.fetch_user(r['user_id'])
                except discord.HTTPException:
                    user = None
            delivered = False
            if user:
                try:
                    await user.send(embed=embed('⏰ NEXUS • LEMBRETE', f"{clip(r['message'], 1800)}\n\nAgendado: <t:{int(r['due_at'].timestamp())}:F>"))
                    delivered = True
                except discord.HTTPException:
                    pass
            if not delivered and r['channel_id']:
                ch = self.bot.get_channel(r['channel_id'])
                if ch:
                    try:
                        await ch.send(f"<@{r['user_id']}> ⏰ Lembrete: {clip(r['message'], 1500)}", allowed_mentions=discord.AllowedMentions(users=True))
                        delivered = True
                    except discord.HTTPException:
                        pass
            await self.pool.execute('UPDATE nexus_reminders SET delivered=$2 WHERE id=$1', r['id'], delivered)

    @reminder_loop.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    @group_1.command(name='lembrete', description='Cria lembrete pessoal para daqui a minutos.')
    async def reminder_create(self, inter, minutos: app_commands.Range[int, 1, 43200], mensagem: str):
        due = datetime.now(timezone.utc) + timedelta(minutes=minutos)
        rid = await self.pool.fetchval('INSERT INTO nexus_reminders(guild_id,user_id,channel_id,message,due_at) VALUES($1,$2,$3,$4,$5) RETURNING id', inter.guild.id, inter.user.id, inter.channel.id, clip(mensagem, 1800), due)
        await reply(inter, f'⏰ Lembrete **#{rid}** criado. <t:{int(due.timestamp())}:R>')

    @group_1.command(name='lembretes', description='Lista seus lembretes pendentes.')
    async def reminders_list(self, inter):
        rows = await self.pool.fetch('SELECT id,message,due_at FROM nexus_reminders WHERE guild_id=$1 AND user_id=$2 AND sent=FALSE ORDER BY due_at LIMIT 20', inter.guild.id, inter.user.id)
        e = embed('⏰ NEXUS • SEUS LEMBRETES', f'{len(rows)} lembretes pendentes')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <t:{int(r['due_at'].timestamp())}:R>", value=clip(r['message'], 400), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='lembrete_cancelar', description='Cancela lembrete pessoal por ID.')
    async def reminder_cancel(self, inter, lembrete_id: int):
        res = await self.pool.execute('DELETE FROM nexus_reminders WHERE guild_id=$1 AND user_id=$2 AND id=$3 AND sent=FALSE', inter.guild.id, inter.user.id, lembrete_id)
        await reply(inter, 'Lembrete cancelado.' if res.endswith('1') else 'Lembrete não encontrado ou já enviado.')

    @group_1.command(name='cmd_personalizado_criar', description='Cria comando de texto personalizado para o servidor (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def custom_create(self, inter, nome: str, resposta: str):
        name = nome.lower().strip().replace(' ', '_')
        if not re.fullmatch('[a-z0-9_-]{1,32}', name):
            return await reply(inter, 'Nome: letras minúsculas, números, hífen e underline (até 32).')
        if name in {'help', 'nexus', 'mod', 'logs', 'afk', 'afk_sair', 'daily', 'work', 'wallet', 'pay', 'rank', 'shop'}:
            return await reply(inter, 'Este nome é reservado pelo Nexus.')
        await self.pool.execute('INSERT INTO nexus_custom_commands(guild_id,name,response,created_by) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,name) DO UPDATE SET response=EXCLUDED.response,created_by=EXCLUDED.created_by,updated_at=NOW()', inter.guild.id, name, clip(resposta, 1800), inter.user.id)
        await reply(inter, f'🧩 Comando `. {name}` (sem espaço) salvo. Resposta configurada.')

    @group_1.command(name='cmd_personalizado_remover', description='Remove comando de texto personalizado.')
    @app_commands.checks.has_permissions(administrator=True)
    async def custom_remove(self, inter, nome: str):
        name = nome.lower().strip()
        res = await self.pool.execute('DELETE FROM nexus_custom_commands WHERE guild_id=$1 AND name=$2', inter.guild.id, name)
        await reply(inter, 'Comando removido.' if res.endswith('1') else 'Comando não encontrado.')

    @group_1.command(name='cmd_personalizados', description='Lista comandos personalizados do servidor.')
    async def custom_list(self, inter):
        rows = await self.pool.fetch('SELECT name,response,created_by FROM nexus_custom_commands WHERE guild_id=$1 ORDER BY name LIMIT 30', inter.guild.id)
        e = embed('🧩 NEXUS • COMANDOS PERSONALIZADOS', f'{len(rows)} comandos (prefixo ponto)')
        for r in rows:
            e.add_field(name=f".{r['name']}", value=clip(r['response'], 250), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='nota_staff', description='Registra nota interna sobre membro (staff).')
    async def note_add(self, inter, membro: discord.User, nota: str):
        if not await self.allowed_staff(inter):
            return
        nid = await self.pool.fetchval('INSERT INTO nexus_staff_notes(guild_id,user_id,author_id,note) VALUES($1,$2,$3,$4) RETURNING id', inter.guild.id, membro.id, inter.user.id, clip(nota, 1500))
        await reply(inter, f'📝 Nota interna **#{nid}** registrada para {membro.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Nota staff registrada', {'note_id': nid, 'target': membro.id, 'note': nota})

    @group_1.command(name='nota_staff_listar', description='Consulta notas internas de membro (staff).')
    async def note_list(self, inter, membro: discord.User):
        if not await self.allowed_staff(inter):
            return
        rows = await self.pool.fetch('SELECT id,author_id,note,created_at FROM nexus_staff_notes WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15', inter.guild.id, membro.id)
        e = embed(f'📝 NEXUS • NOTAS DE {membro}', f'{len(rows)} notas internas')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <t:{int(r['created_at'].timestamp())}:R> • <@{r['author_id']}>", value=clip(r['note'], 650), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='nota_staff_remover', description='Apaga nota interna por ID (staff).')
    async def note_remove(self, inter, nota_id: int):
        if not await self.allowed_staff(inter):
            return
        res = await self.pool.execute('DELETE FROM nexus_staff_notes WHERE guild_id=$1 AND id=$2', inter.guild.id, nota_id)
        await reply(inter, 'Nota removida.' if res.endswith('1') else 'Nota não encontrada.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Nota staff removida', {'note_id': nota_id})

    @group_1.command(name='warn', description='Registra advertência formal para membro.')
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_cmd(self, inter, membro: discord.Member, motivo: str):
        ok, msg = hierarchy(inter.user, membro, inter.guild.me)
        if not ok:
            return await reply(inter, msg)
        core = self.bot.get_cog('Systems')
        cid = await core.case(inter.guild.id, membro.id, inter.user.id, 'warn', motivo)
        await core.dm(membro, 'Advertência', motivo, cid)
        await reply(inter, f'⚠️ Advertência registrada em **#{cid}** para {membro.mention}.')
        await core.audit(inter.guild, inter.user.id, 'Advertência aplicada', {'case_id': cid, 'target': membro.id, 'reason': motivo}, 'log_punishment_channel_id', GOLD)

    @group_1.command(name='warns', description='Lista advertências registradas para membro.')
    async def warns_list(self, inter, membro: discord.User):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg) and inter.user.id != membro.id:
            return await reply(inter, 'Sem permissão para consultar advertências de terceiros.')
        rows = await self.pool.fetch("SELECT id,moderator_id,reason,created_at,active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 AND action='warn' ORDER BY id DESC LIMIT 20", inter.guild.id, membro.id)
        e = embed(f'⚠️ NEXUS • ADVERTÊNCIAS ({membro})', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {('ativa' if r['active'] else 'revogada')} • <t:{int(r['created_at'].timestamp())}:R>", value=f"Moderador: <@{r['moderator_id']}>\n{clip(r['reason'], 500)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='warn_revogar', description='Revoga advertência registrada por ID (staff).')
    async def warn_revoke(self, inter, caso_id: int, justificativa: str):
        if not await self.allowed_staff(inter):
            return
        row = await self.pool.fetchrow("SELECT * FROM sistemas_cases WHERE guild_id=$1 AND id=$2 AND action='warn' AND active=TRUE", inter.guild.id, caso_id)
        if not row:
            return await reply(inter, 'Advertência ativa não encontrada.')
        await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        await reply(inter, f'Advertência **#{caso_id}** revogada.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Advertência revogada', {'case_id': caso_id, 'target': row['user_id'], 'reason': justificativa}, 'log_punishment_channel_id', GREEN)

    @group_1.command(name='ban_lista', description='Lista banimentos do servidor (staff).')
    async def ban_list(self, inter):
        if not await self.allowed_staff(inter):
            return
        bans = []
        async for entry in inter.guild.bans(limit=50):
            bans.append(entry)
        e = embed('🔨 NEXUS • BANIMENTOS', f'{len(bans)} usuários na amostra (limite de 50)')
        for b in bans:
            e.add_field(name=f'{b.user} • {b.user.id}', value=clip(b.reason or 'Sem motivo informado', 250), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='voz_mover', description='Move membro para outro canal de voz (staff).')
    async def voice_move(self, inter, membro: discord.Member, destino: discord.VoiceChannel):
        if not await self.allowed_staff(inter):
            return
        if not membro.voice:
            return await reply(inter, 'Membro não está conectado em voz.')
        await membro.move_to(destino, reason=f'Movido por {inter.user.id}')
        await reply(inter, f'🔊 {membro.mention} movido para {destino.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Membro movido em voz', {'member': membro.id, 'destination': destino.id})

    @group_1.command(name='voz_desconectar', description='Desconecta membro de canal de voz (staff).')
    async def voice_disconnect(self, inter, membro: discord.Member, motivo: str='Desconexão da equipe'):
        if not await self.allowed_staff(inter):
            return
        if not membro.voice:
            return await reply(inter, 'Membro não está conectado em voz.')
        await membro.move_to(None, reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f'🔌 {membro.mention} desconectado da voz.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Membro desconectado de voz', {'member': membro.id, 'reason': motivo})

    @group_1.command(name='voz_mute', description='Mute de voz Discord para membro (staff).')
    async def voice_mute(self, inter, membro: discord.Member, ativar: bool, motivo: str='Moderação'):
        if not await self.allowed_staff(inter):
            return
        if not membro.voice:
            return await reply(inter, 'Membro não está conectado em voz.')
        await membro.edit(mute=ativar, reason=f'{inter.user.id}: {motivo}')
        await reply(inter, f"🎙️ Mute de servidor {('ativado' if ativar else 'removido')} para {membro.mention}.")
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Mute de voz alterado', {'member': membro.id, 'enabled': ativar, 'reason': motivo})

    @group_1.command(name='cargo_criar', description='Cria cargo no servidor (administrador).')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_create(self, inter, nome: str, cor_hex: str='7C3AED', hoist: bool=False, mentionable: bool=False):
        raw = cor_hex.strip().replace('#', '')
        if not re.fullmatch('[0-9a-fA-F]{6}', raw):
            return await reply(inter, 'Cor deve ser HEX de seis dígitos, ex. `7C3AED`.')
        role = await inter.guild.create_role(name=clip(nome, 100), colour=discord.Colour(int(raw, 16)), hoist=hoist, mentionable=mentionable, reason=f'Criado por {inter.user.id}')
        await reply(inter, f'🎭 Cargo criado: {role.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargo criado via comando', {'role_id': role.id, 'name': role.name, 'hex': raw})

    @group_1.command(name='cargo_editar', description='Edita cor, nome e propriedades de cargo.')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_edit(self, inter, cargo: discord.Role, nome: Optional[str]=None, cor_hex: Optional[str]=None, hoist: Optional[bool]=None, mentionable: Optional[bool]=None):
        if cargo >= inter.guild.me.top_role:
            return await reply(inter, 'O bot não pode editar cargo igual ou acima de seu cargo mais alto.')
        changes = {}
        if nome:
            changes['name'] = clip(nome, 100)
        if cor_hex:
            raw = cor_hex.strip().replace('#', '')
            if not re.fullmatch('[0-9a-fA-F]{6}', raw):
                return await reply(inter, 'HEX inválido.')
            changes['colour'] = discord.Colour(int(raw, 16))
        if hoist is not None:
            changes['hoist'] = hoist
        if mentionable is not None:
            changes['mentionable'] = mentionable
        if not changes:
            return await reply(inter, 'Informe pelo menos uma alteração.')
        await cargo.edit(reason=f'Editado por {inter.user.id}', **changes)
        await reply(inter, f'✏️ Cargo {cargo.mention} atualizado.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargo editado via comando', {'role_id': cargo.id, 'changes': str(changes)})

    @group_1.command(name='canal_texto_criar', description='Cria canal de texto (gerenciar canais).')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def text_channel_create(self, inter, nome: str, categoria: Optional[discord.CategoryChannel]=None, topico: str=''):
        channel = await inter.guild.create_text_channel(name=clip(nome, 90), category=categoria, topic=clip(topico, 1024) if topico else None, reason=f'Criado por {inter.user.id}')
        await reply(inter, f'💬 Canal criado: {channel.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Canal texto criado via comando', {'channel_id': channel.id, 'name': channel.name})

    @group_1.command(name='canal_voz_criar', description='Cria canal de voz (gerenciar canais).')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def voice_channel_create(self, inter, nome: str, categoria: Optional[discord.CategoryChannel]=None, limite: app_commands.Range[int, 0, 99]=0):
        channel = await inter.guild.create_voice_channel(name=clip(nome, 90), category=categoria, user_limit=limite, reason=f'Criado por {inter.user.id}')
        await reply(inter, f'🔊 Canal de voz criado: {channel.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Canal voz criado via comando', {'channel_id': channel.id, 'name': channel.name})

    @group_1.command(name='canal_excluir', description='Exclui canal selecionado (gerenciar canais).')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_delete(self, inter, canal: discord.abc.GuildChannel, motivo: str):
        if canal.id == inter.channel.id:
            await inter.response.send_message('O canal atual será excluído após confirmação da operação.', ephemeral=True)
        else:
            await inter.response.send_message(f'Canal {canal.name} selecionado para exclusão.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Canal excluído via comando', {'channel_id': canal.id, 'name': canal.name, 'reason': motivo}, 'log_server_channel_id', RED)
        await canal.delete(reason=f'{inter.user.id}: {motivo}')

    @group_1.command(name='estatisticas_membros', description='Estatísticas de membros e status online do servidor.')
    async def member_stats(self, inter):
        g = inter.guild
        members = list(g.members)
        bots = sum((m.bot for m in members))
        humans = len(members) - bots
        online = sum((m.status != discord.Status.offline for m in members))
        e = embed('📈 NEXUS • ESTATÍSTICAS', f'**Total no cache:** {len(members):,}\n**Humanos:** {humans:,}\n**Bots:** {bots:,}\n**Online/ocupado/ausente:** {online:,}\n**Canais texto:** {len(g.text_channels)}\n**Canais voz:** {len(g.voice_channels)}\n**Cargos:** {len(g.roles)}')
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='emoji_lista', description='Lista emojis personalizados do servidor.')
    async def emoji_list(self, inter):
        emojis = list(inter.guild.emojis)
        e = embed('😀 NEXUS • EMOJIS', f'{len(emojis)} emojis')
        for i in range(0, min(len(emojis), 80), 20):
            e.add_field(name=f'Emojis {i + 1}-{min(i + 20, len(emojis))}', value=' '.join((str(x) for x in emojis[i:i + 20])), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='webhook_criar', description='Cria webhook no canal atual (gerenciar webhooks).')
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def webhook_create(self, inter, nome: str):
        hook = await inter.channel.create_webhook(name=clip(nome, 80), reason=f'Criado por {inter.user.id}')
        await reply(inter, 'Webhook criado. A URL será enviada em DM; trate como segredo.')
        try:
            await inter.user.send(f'Webhook `{hook.name}` criado em {inter.guild.name}/{inter.channel.name}. URL secreta:\n{hook.url}')
        except discord.HTTPException:
            await reply(inter, 'Não consegui enviar DM; URL não foi exibida aqui para evitar vazamento. Remova o webhook e tente novamente com DM aberta.')
            await hook.delete(reason='DM falhou; remoção de webhook secreto')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Webhook criado', {'webhook_id': hook.id, 'channel': inter.channel.id, 'name': hook.name})

    @group_1.command(name='webhook_listar', description='Lista webhooks do servidor sem exibir URLs.')
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def webhook_list(self, inter):
        hooks = await inter.guild.webhooks()
        e = embed('🔗 NEXUS • WEBHOOKS', f'{len(hooks)} webhooks')
        for h in hooks:
            e.add_field(name=h.name, value=f'ID: `{h.id}` • Canal: <#{h.channel_id or 0}> • Criado: <t:{int(h.created_at.timestamp())}:R>', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='webhook_remover', description='Remove webhook por ID.')
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def webhook_delete(self, inter, webhook_id: str, motivo: str='Remoção solicitada'):
        if not webhook_id.isdigit():
            return await reply(inter, 'ID inválido.')
        try:
            hook = await self.bot.fetch_webhook(int(webhook_id))
        except discord.NotFound:
            return await reply(inter, 'Webhook não encontrado.')
        if hook.guild_id != inter.guild.id:
            return await reply(inter, 'Webhook não pertence a este servidor.')
        await hook.delete(reason=f'{inter.user.id}: {motivo}')
        await reply(inter, 'Webhook removido.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Webhook removido', {'webhook_id': webhook_id, 'reason': motivo})

    @group_2.command(name='backup_json', description='Gera arquivo JSON com backup de configurações e dados selecionados (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_json(self, inter):
        await inter.response.defer(ephemeral=True)
        core = self.bot.get_cog('Systems')
        cfg = await core.config(inter.guild.id)
        tables = ['sistemas_cases', 'sistemas_requests', 'sistemas_appeals', 'sistemas_reports', 'sistemas_suggestions', 'sistemas_xp', 'nexus_quarantine', 'nexus_wallets', 'nexus_economy_tx', 'nexus_products', 'nexus_orders', 'nexus_staff_tasks', 'nexus_events', 'nexus_custom_commands', 'nexus_staff_notes']
        payload = {'guild_id': inter.guild.id, 'generated_at': datetime.now(timezone.utc).isoformat(), 'config': cfg, 'tables': {}}
        for table in tables:
            rows = await self.pool.fetch(f'SELECT * FROM {table} WHERE guild_id=$1 ORDER BY 1 LIMIT 5000', inter.guild.id)
            payload['tables'][table] = [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in dict(r).items()} for r in rows]
        raw = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode('utf-8')
        if len(raw) > 7500000:
            return await inter.followup.send('Backup excede o limite de upload. Use backup de banco/infra.', ephemeral=True)
        file = discord.File(io.BytesIO(raw), filename=f'nexus_backup_{inter.guild.id}_{int(time.time())}.json')
        await inter.followup.send('🗄️ Backup JSON gerado. Armazene com segurança; contém dados administrativos.', file=file, ephemeral=True)

    @group_2.command(name='config_regras', description='Publica mensagem de regras em embed.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def rules_publish(self, inter, canal: discord.TextChannel, titulo: str, regras: str):
        e = embed(f'📜 {clip(titulo, 200)}', clip(regras, 4000))
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
            e.set_image(url=cfg['theme_image_url'])
        await canal.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, f'📜 Regras publicadas em {canal.mention}.')

    @group_2.command(name='config_saudacao_teste', description='Testa embed de boas-vindas para o próprio usuário.')
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_test(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        txt = str(cfg.get('welcome_message') or 'Bem-vindo {member} ao {server}').replace('{member}', inter.user.mention).replace('{server}', inter.guild.name)
        e = embed('👋 NEXUS • TESTE DE BOAS-VINDAS', txt)
        e.set_thumbnail(url=inter.user.display_avatar.url)
        if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
            e.set_image(url=cfg['theme_image_url'])
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='staff_online', description='Lista equipe com status de atividade/voz.')
    async def staff_online(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        role_ids = set(cfg.get('staff_role_ids') or [])
        staff_members = [m for m in inter.guild.members if any((r.id in role_ids for r in m.roles))]
        e = embed('🛡️ NEXUS • STAFF PRESENTE', f'{len(staff_members)} membros de staff encontrados')
        for m in staff_members[:30]:
            state = '🔊 em voz' if m.voice and m.voice.channel else '🟢 online' if m.status != discord.Status.offline else '⚫ offline'
            e.add_field(name=m.display_name, value=f'{state} • {m.top_role.mention}', inline=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='staff_reuniao', description='Registra uma reunião de equipe no canal escolhido.')
    async def staff_meeting(self, inter, canal: discord.TextChannel, titulo: str, agenda: str, data_iso_utc: str):
        if not await self.allowed_staff(inter):
            return
        try:
            when = datetime.fromisoformat(data_iso_utc.replace('Z', '+00:00'))
        except ValueError:
            return await reply(inter, 'Data ISO inválida.')
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)
        e = embed(f'🗓️ REUNIÃO STAFF • {clip(titulo, 180)}', f'**Agenda:**\n{clip(agenda, 2500)}\n\n**Data:** <t:{int(when.timestamp())}:F>\n**Organizador:** {inter.user.mention}')
        await canal.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, 'Reunião publicada.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Reunião staff publicada', {'channel': canal.id, 'title': titulo, 'time': when.isoformat()})

    @group_2.command(name='economia_top', description='Ranking dos maiores saldos NXC.')
    async def economy_top(self, inter):
        rows = await self.pool.fetch('SELECT user_id,balance FROM nexus_wallets WHERE guild_id=$1 ORDER BY balance DESC LIMIT 10', inter.guild.id)
        e = embed('💰 NEXUS • RANKING ECONOMIA', 'Top 10 saldos virtuais')
        for i, r in enumerate(rows, 1):
            e.add_field(name=f"{i}. <@{r['user_id']}>", value=f"{r['balance']:,} NXC", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='economia_historico', description='Consulta últimas transações da economia (staff).')
    async def economy_history(self, inter, membro: discord.User, limite: app_commands.Range[int, 1, 25]=10):
        if not await self.allowed_staff(inter):
            return
        rows = await self.pool.fetch('SELECT from_user,to_user,amount,kind,created_at FROM nexus_economy_tx WHERE guild_id=$1 AND (from_user=$2 OR to_user=$2) ORDER BY id DESC LIMIT $3', inter.guild.id, membro.id, limite)
        e = embed(f'💳 HISTÓRICO • {membro}', f'{len(rows)} transações')
        for r in rows:
            e.add_field(name=f"{r['kind']} • {r['amount']:,} NXC • <t:{int(r['created_at'].timestamp())}:R>", value=f"Origem: <@{r['from_user'] or 0}> • Destino: <@{r['to_user'] or 0}>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='config_niveis', description='Configura mensagem de level up.')
    @app_commands.checks.has_permissions(administrator=True)
    async def level_message_config(self, inter, mensagem: str):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'xp_level_message', clip(mensagem, 1000))
        await reply(inter, 'Mensagem de level up registrada na configuração. Variáveis: `{member}`, `{level}`.')

    @group_2.command(name='canais_lista', description='Lista canais por categoria e tipo.')
    async def channels_list(self, inter):
        g = inter.guild
        e = embed(f'🗂️ {g.name} • CANAIS', f'{len(g.channels)} canais')
        for cat in g.categories[:20]:
            lines = [c.mention for c in cat.channels[:25]]
            e.add_field(name=clip(cat.name, 200), value=clip('\n'.join(lines) or 'Sem canais', 900), inline=False)
        uncategorized = [c.mention for c in g.channels if c.category is None]
        if uncategorized:
            e.add_field(name='Sem categoria', value=clip('\n'.join(uncategorized), 900), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='cargo_lista', description='Lista cargos e membros aproximados por cargo.')
    async def roles_list(self, inter):
        roles = sorted(inter.guild.roles, reverse=True, key=lambda r: r.position)
        e = embed('🎭 NEXUS • CARGOS', f'{len(roles)} cargos')
        for r in roles[:25]:
            e.add_field(name=f'{r.name} • ID {r.id}', value=f"Posição {r.position} • Cor {r.colour} • Menção {('sim' if r.mentionable else 'não')}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='membro_convidar', description='Consulta convites em cache para usuário (quando disponíveis).')
    async def invite_lookup(self, inter, membro: discord.Member):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Consulta restrita à equipe.')
        row = await self.pool.fetchrow('SELECT code,inviter_id,uses FROM nexus_invites WHERE guild_id=$1 AND inviter_id=$2 ORDER BY uses DESC LIMIT 1', inter.guild.id, membro.id)
        if not row:
            return await reply(inter, 'Sem registro de convite para este membro. Rastreamento de convites depende de cache/inicialização.')
        await reply(inter, f"Convite registrado: `{row['code']}` • usos contabilizados: **{row['uses']}**.")

    @group_2.command(name='mensagem_contagem', description='Mostra contagem de mensagens em cache do bot (estimativa).')
    async def message_count(self, inter):
        cached = len(getattr(self.bot, 'cached_messages', []) or [])
        await reply(inter, f'📨 Mensagens em cache pelo bot: **{cached}**. Este número não é a contagem total do servidor.')

    @group_2.command(name='nexus_config_resumo', description='Mostra resumo de configuração atual do Nexus (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def config_summary(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        channel_keys = ['request_channel_id', 'appeal_channel_id', 'report_channel_id', 'suggestion_channel_id', 'welcome_channel_id', 'log_server_channel_id', 'log_member_channel_id', 'log_role_channel_id', 'log_punishment_channel_id', 'log_internal_channel_id']
        fields = []
        for k in channel_keys:
            fields.append(f"**{k}:** {(f'<#{cfg[k]}>' if cfg.get(k) else 'não configurado')}")
        fields.extend([f"**Staff roles:** {cfg.get('staff_role_ids') or []}", f"**Quarantine role:** {cfg.get('quarantine_role_id') or 'não configurado'}", f"**Anti-raid:** {cfg.get('anti_raid_enabled')} • threshold {cfg.get('anti_raid_threshold')}", f"**Anti-nuke alerts:** {cfg.get('anti_nuke_enabled')}", f"**AutoMod:** spam={cfg.get('anti_spam_enabled')} links={cfg.get('anti_links_enabled')} invites={cfg.get('anti_invites_enabled')}", f"**XP:** {cfg.get('xp_enabled')}"])
        await inter.response.send_message(embed=embed('⚙️ NEXUS • CONFIGURAÇÃO', clip('\n'.join(fields), 4000)), ephemeral=True)

    @group_2.command(name='bot_ping', description='Mede latência de gateway.')
    async def ping_cmd(self, inter):
        start = time.monotonic()
        await inter.response.defer(ephemeral=True)
        latency = (time.monotonic() - start) * 1000
        await inter.followup.send(f'🏓 Gateway: **{self.bot.latency * 1000:.1f} ms** • resposta local: **{latency:.1f} ms**', ephemeral=True)

    @group_2.command(name='staff_registrar', description='Registra membro na lista persistente de staff.')
    async def staff_register(self, inter, membro: discord.Member, cargo_staff: str='Equipe'):
        if not await self.allowed_staff(inter):
            return
        await self.pool.execute('INSERT INTO sistemas_staff(guild_id,user_id,active,last_seen,role_name) VALUES($1,$2,TRUE,NOW(),$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET active=TRUE,last_seen=NOW(),role_name=EXCLUDED.role_name', inter.guild.id, membro.id, clip(cargo_staff, 80))
        await reply(inter, f'🛡️ {membro.mention} registrado no roster de staff.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Staff registrado', {'member': membro.id, 'role_name': cargo_staff})

    @group_2.command(name='staff_remover', description='Remove membro do roster persistente de staff.')
    async def staff_remove(self, inter, membro: discord.User):
        if not await self.allowed_staff(inter):
            return
        await self.pool.execute('UPDATE sistemas_staff SET active=FALSE WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        await reply(inter, 'Registro de staff desativado.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Staff desativado no roster', {'member': membro.id})

    @group_2.command(name='staff_roster', description='Lista roster persistente de staff.')
    async def staff_roster(self, inter):
        if not await self.allowed_staff(inter):
            return
        rows = await self.pool.fetch('SELECT user_id,role_name,last_seen FROM sistemas_staff WHERE guild_id=$1 AND active=TRUE ORDER BY role_name,user_id LIMIT 50', inter.guild.id)
        e = embed('🛡️ NEXUS • ROSTER STAFF', f'{len(rows)} registros ativos')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}> • {r['role_name'] or 'Staff'}", value=f"Última atualização: <t:{int(r['last_seen'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_2.command(name='config_idioma', description='Define idioma de apresentação (pt-BR ou en).')
    @app_commands.checks.has_permissions(administrator=True)
    async def language_config(self, inter, idioma: str):
        language = idioma.lower().strip()
        if language not in ('pt-br', 'en'):
            return await reply(inter, 'Idiomas suportados neste módulo: `pt-br` e `en`. (A tradução completa é gradual.)')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'language', language)
        await reply(inter, f'🌐 Preferência salva: **{language}**. Algumas mensagens ainda permanecem em português.')

    @group_2.command(name='config_fuso', description='Define fuso horário IANA usado em futuras ferramentas de agenda.')
    @app_commands.checks.has_permissions(administrator=True)
    async def timezone_config(self, inter, fuso: str):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(fuso)
        except Exception:
            return await reply(inter, 'Fuso inválido. Exemplo: `America/Sao_Paulo`.')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'timezone', fuso)
        await reply(inter, f'🕒 Fuso salvo: `{fuso}`. Datas de agendamento atuais usam ISO/UTC explicitamente.')

    @group_2.command(name='config_anti_invite', description='Liga/desliga filtro de convites Discord.')
    @app_commands.checks.has_permissions(administrator=True)
    async def anti_invite_config(self, inter, ativar: bool):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'anti_invites_enabled', ativar)
        await reply(inter, f"🛡️ Filtro de convite Discord {('ativado' if ativar else 'desativado')}.")

    @group_2.command(name='config_anti_link', description='Liga/desliga filtro de links.')
    @app_commands.checks.has_permissions(administrator=True)
    async def anti_link_config(self, inter, ativar: bool):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'anti_links_enabled', ativar)
        await reply(inter, f"🔗 Filtro de links {('ativado' if ativar else 'desativado')}.")

    @group_2.command(name='config_anti_spam', description='Liga/desliga detecção de spam.')
    @app_commands.checks.has_permissions(administrator=True)
    async def anti_spam_config(self, inter, ativar: bool):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'anti_spam_enabled', ativar)
        await reply(inter, f"📨 Filtro de spam {('ativado' if ativar else 'desativado')}.")

    @group_2.command(name='config_anti_raid', description='Liga/desliga alerta de entrada em massa.')
    @app_commands.checks.has_permissions(administrator=True)
    async def anti_raid_config(self, inter, ativar: bool, limite: app_commands.Range[int, 3, 30]=6, janelaseg: app_commands.Range[int, 5, 60]=12):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'anti_raid_enabled', ativar)
        await core.setcfg(inter.guild.id, 'anti_raid_threshold', limite)
        await core.setcfg(inter.guild.id, 'anti_raid_window_seconds', janelaseg)
        await reply(inter, f"🚨 Anti-raid {('ativado' if ativar else 'desativado')}. Limite: {limite} entradas em {janelaseg}s. O sistema gera alerta, não lockdown automático.")

    @group_2.command(name='config_anti_nuke', description='Liga/desliga alertas de exclusão de canais/cargos.')
    @app_commands.checks.has_permissions(administrator=True)
    async def anti_nuke_config(self, inter, ativar: bool, limite: app_commands.Range[int, 2, 20]=4):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'anti_nuke_enabled', ativar)
        await core.setcfg(inter.guild.id, 'anti_nuke_threshold', limite)
        await reply(inter, f"🧯 Alertas anti-nuke {('ativados' if ativar else 'desativados')}. Monitoramento limitado às ações implementadas; sem contenção automática.")

    @group_3.command(name='logs_config', description='Configura canal único de log para categorias não preenchidas.')
    @app_commands.checks.has_permissions(administrator=True)
    async def log_channel_default(self, inter, canal: discord.TextChannel):
        core = self.bot.get_cog('Systems')
        for key in ['log_server_channel_id', 'log_member_channel_id', 'log_role_channel_id', 'log_punishment_channel_id', 'log_internal_channel_id']:
            await core.setcfg(inter.guild.id, key, canal.id)
        await reply(inter, f'📜 Todas as categorias de log apontam para {canal.mention}.')

    @group_3.command(name='membro_desconhecido', description='Consulta ID de usuário e tenta buscar dados públicos.')
    async def user_lookup(self, inter, user_id: str):
        if not user_id.isdigit():
            return await reply(inter, 'ID inválido.')
        try:
            u = await self.bot.fetch_user(int(user_id))
        except discord.NotFound:
            return await reply(inter, 'Usuário não encontrado pelo Discord API.')
        e = embed(f'🔎 NEXUS • USUÁRIO {u}', f"ID: `{u.id}`\nCriado: <t:{int(u.created_at.timestamp())}:F>\nBot: {('sim' if u.bot else 'não')}")
        e.set_thumbnail(url=u.display_avatar.url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='config_cargo_quarentena', description='Configura cargo e aplica bloqueio básico a todos canais existentes.')
    @app_commands.checks.has_permissions(administrator=True)
    async def quarantine_role_setup(self, inter, cargo: discord.Role, aplicar_canais_existentes: bool=False):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'quarantine_role_id', cargo.id)
        updated = 0
        failed = 0
        if aplicar_canais_existentes:
            for channel in inter.guild.channels:
                try:
                    await channel.set_permissions(cargo, view_channel=False, send_messages=False, connect=False, reason=f'Configuração quarentena por {inter.user.id}')
                    updated += 1
                except discord.HTTPException:
                    failed += 1
        await reply(inter, f'🔐 Cargo de quarentena configurado. Overwrites aplicados: **{updated}**; falhas: **{failed}**.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargo quarentena configurado', {'role': cargo.id, 'applied_channels': updated, 'failed': failed})

    @group_3.command(name='config_remote_admin', description='Configura IDs autorizados ao painel remoto.')
    @app_commands.checks.has_permissions(administrator=True)
    async def remote_admin_config(self, inter, ids_csv: str, ativar: bool=True):
        ids = []
        for part in ids_csv.split(','):
            part = part.strip()
            if part and part.isdigit():
                ids.append(int(part))
            elif part:
                return await reply(inter, 'Formato inválido. IDs numéricos separados por vírgula.')
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'remote_admin_ids', sorted(set(ids)))
        await core.setcfg(inter.guild.id, 'remote_enabled', ativar and bool(ids))
        await reply(inter, f"🛰️ Remote Ops {('ativado' if ativar and ids else 'desativado')}. IDs autorizados: {len(set(ids))}.")
        await core.audit(inter.guild, inter.user.id, 'Remote Ops configurado', {'enabled': ativar, 'ids': ids})

    @group_3.command(name='config_xp_reset', description='Reseta XP de um membro (staff).')
    async def xp_reset(self, inter, membro: discord.User):
        if not await self.allowed_staff(inter):
            return
        await self.pool.execute('DELETE FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        await reply(inter, f'✨ XP de {membro.mention} resetado.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'XP resetado', {'user': membro.id})

    @group_3.command(name='config_xp_add', description='Adiciona XP manualmente (staff).')
    async def xp_add(self, inter, membro: discord.User, quantidade: app_commands.Range[int, 1, 1000000]):
        if not await self.allowed_staff(inter):
            return
        await self.pool.execute('INSERT INTO sistemas_xp(guild_id,user_id,xp,level,last_message_at) VALUES($1,$2,$3,$4,NOW()) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=sistemas_xp.xp+$3,level=FLOOR(SQRT(sistemas_xp.xp+$3)/5)::int', inter.guild.id, membro.id, quantidade, int(quantidade ** 0.5 // 5))
        await reply(inter, f'✨ {quantidade:,} XP adicionados para {membro.mention}.')

    @group_3.command(name='config_xp_remove', description='Remove XP de membro (staff).')
    async def xp_remove(self, inter, membro: discord.User, quantidade: app_commands.Range[int, 1, 1000000]):
        if not await self.allowed_staff(inter):
            return
        await self.pool.execute('UPDATE sistemas_xp SET xp=GREATEST(xp-$3,0),level=FLOOR(SQRT(GREATEST(xp-$3,0))/5)::int WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id, quantidade)
        await reply(inter, f'✨ XP ajustado para {membro.mention}.')

    @group_3.command(name='status_membro', description='Consulta status de membro e roles (staff).')
    async def member_status(self, inter, membro: discord.Member):
        if not await self.allowed_staff(inter):
            return
        e = embed(f'📋 NEXUS • STATUS {membro.display_name}', f"ID: `{membro.id}`\nBot: {membro.bot}\nStatus: {membro.status}\nTimeout: {(f'<t:{int(membro.timed_out_until.timestamp())}:R>' if membro.timed_out_until else 'não')}\nVoice: {(membro.voice.channel.mention if membro.voice and membro.voice.channel else 'não conectado')}")
        e.set_thumbnail(url=membro.display_avatar.url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='config_sugestao_canal', description='Configura canal de sugestões.')
    @app_commands.checks.has_permissions(administrator=True)
    async def suggestion_channel_config(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'suggestion_channel_id', canal.id)
        await reply(inter, f'💡 Canal de sugestões: {canal.mention}.')

    @group_3.command(name='config_denuncia_canal', description='Configura canal de denúncias.')
    @app_commands.checks.has_permissions(administrator=True)
    async def report_channel_config(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'report_channel_id', canal.id)
        await reply(inter, f'🛡️ Canal de denúncias: {canal.mention}.')

    @group_3.command(name='config_apelacao_canal', description='Configura canal de apelações.')
    @app_commands.checks.has_permissions(administrator=True)
    async def appeal_channel_config(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'appeal_channel_id', canal.id)
        await reply(inter, f'📨 Canal de apelações: {canal.mention}.')

    @group_3.command(name='config_solicitacao_canal', description='Configura canal de solicitações de punição.')
    @app_commands.checks.has_permissions(administrator=True)
    async def request_channel_config(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'request_channel_id', canal.id)
        await reply(inter, f'⚖️ Canal de solicitações: {canal.mention}.')

    @group_3.command(name='nexus_privacidade', description='Exibe resumo de dados armazenados pelos sistemas Nexus.')
    async def privacy_info(self, inter):
        e = embed('🔒 NEXUS • PRIVACIDADE', 'Os sistemas podem armazenar IDs de Discord, registros de moderação, conteúdo de denúncias/sugestões, XP, saldo virtual, tarefas e configurações de servidor. Dados são usados para operação dos módulos e logs configurados.\n\nAdministradores devem configurar retenção, acesso aos canais de logs e backups. Não compartilhe arquivos de backup publicamente. Para solicitações de remoção, a equipe do servidor deve avaliar os registros e obrigações de moderação.')
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='nexus_termos_economia', description='Exibe regras e aviso da economia virtual.')
    async def economy_terms(self, inter):
        e = embed('💰 NEXUS • ECONOMIA VIRTUAL', 'NXC é moeda virtual interna do servidor. Não é dinheiro real, não pode ser convertida em moeda fiduciária, não possui valor financeiro e não representa pagamento. Transferências e compras são internas; staff deve evitar alterações arbitrárias e registrar motivo. Pagamentos reais não estão conectados neste módulo.')
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_3.command(name='nexus_sistemas', description='Lista os módulos atualmente carregados.')
    async def systems_status(self, inter):
        loaded = ', '.join(sorted(self.bot.cogs.keys()))
        e = embed('🧩 NEXUS • MÓDULOS', clip(loaded, 3000))
        e.add_field(name='Sistemas principais', value='Moderação • AutoMod • logs • economia virtual • XP • staff • sugestões • denúncias • eventos • sorteios • voz temporária • AFK • backups • anúncios agendados • Remote Ops • tarefas • webhooks • lembretes • comandos customizados', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

async def _load_operations(bot, pool):
    if bot.get_cog('NexusOperations') is None:
        await bot.add_cog(NexusOperations(bot, pool))

class NexusCommunity(commands.Cog):
    group_1 = app_commands.Group(name='community', description='NexusCommunity commands (community)')
    group_2 = app_commands.Group(name='social', description='NexusCommunity commands (social)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.birthday_loop.start()

    def cog_unload(self):
        self.birthday_loop.cancel()

    async def staff_gate(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Ação reservada à equipe.')
        return False

    @tasks.loop(hours=1)
    async def birthday_loop(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        rows = await self.pool.fetch('SELECT guild_id,user_id,month,day,last_year FROM nexus_birthdays WHERE month=$1 AND day=$2 AND last_year<$3', now.month, now.day, now.year)
        for r in rows:
            g = self.bot.get_guild(r['guild_id'])
            if not g:
                continue
            cfg = await self.bot.get_cog('Systems').config(g.id)
            ch = g.get_channel(cfg.get('birthday_channel_id')) if cfg.get('birthday_channel_id') else g.get_channel(cfg.get('welcome_channel_id'))
            if ch:
                try:
                    await ch.send(embed=embed('🎂 NEXUS • ANIVERSÁRIO', f"Hoje é dia de celebrar <@{r['user_id']}>! Desejamos muita felicidade e um excelente novo ciclo. 🎉"), allowed_mentions=discord.AllowedMentions(users=True))
                except discord.HTTPException:
                    pass
            await self.pool.execute('UPDATE nexus_birthdays SET last_year=$3 WHERE guild_id=$1 AND user_id=$2', r['guild_id'], r['user_id'], now.year)

    @birthday_loop.before_loop
    async def before_birthday(self):
        await self.bot.wait_until_ready()

    @group_1.command(name='aniversario_set', description='Registra seu aniversário no servidor (dia e mês).')
    async def birthday_set(self, inter, dia: app_commands.Range[int, 1, 31], mes: app_commands.Range[int, 1, 12]):
        try:
            datetime(2000, mes, dia)
        except ValueError:
            return await reply(inter, 'Dia inválido para o mês informado.')
        await self.pool.execute('INSERT INTO nexus_birthdays(guild_id,user_id,month,day,last_year) VALUES($1,$2,$3,$4,0) ON CONFLICT(guild_id,user_id) DO UPDATE SET month=EXCLUDED.month,day=EXCLUDED.day,last_year=0', inter.guild.id, inter.user.id, mes, dia)
        await reply(inter, '🎂 Aniversário registrado! A equipe pode configurar canal para avisos.')

    @group_1.command(name='aniversario_remover', description='Remove seu aniversário registrado.')
    async def birthday_remove(self, inter):
        res = await self.pool.execute('DELETE FROM nexus_birthdays WHERE guild_id=$1 AND user_id=$2', inter.guild.id, inter.user.id)
        await reply(inter, 'Registro removido.' if res.endswith('1') else 'Você não tinha registro.')

    @group_1.command(name='aniversarios', description='Lista aniversários cadastrados no servidor.')
    async def birthday_list(self, inter):
        rows = await self.pool.fetch('SELECT user_id,month,day FROM nexus_birthdays WHERE guild_id=$1 ORDER BY month,day LIMIT 50', inter.guild.id)
        e = embed('🎂 NEXUS • ANIVERSÁRIOS', f'{len(rows)} aniversários registrados')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}>", value=f"{r['day']:02d}/{r['month']:02d}", inline=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='aniversario_canal', description='Configura canal de avisos de aniversário (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def birthday_channel(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'birthday_channel_id', canal.id)
        await reply(inter, f'🎂 Avisos de aniversário serão enviados em {canal.mention}.')

    @group_1.command(name='tag_criar', description='Cria uma tag pública de texto para o servidor.')
    async def tag_create(self, inter, nome: str, conteudo: str):
        name = nome.lower().strip().replace(' ', '_')
        if not re.fullmatch('[a-z0-9_-]{1,32}', name):
            return await reply(inter, 'Nome inválido: use letras minúsculas, números, hífen e underline.')
        await self.pool.execute('INSERT INTO nexus_tags(guild_id,name,content,owner_id) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,name) DO UPDATE SET content=EXCLUDED.content,owner_id=EXCLUDED.owner_id,updated_at=NOW()', inter.guild.id, name, clip(conteudo, 1800), inter.user.id)
        await reply(inter, f'🏷️ Tag `{name}` criada/atualizada. Use `/tag_ver` para consultar.')

    @group_1.command(name='tag_ver', description='Mostra conteúdo de tag do servidor.')
    async def tag_view(self, inter, nome: str):
        row = await self.pool.fetchrow('SELECT content,owner_id FROM nexus_tags WHERE guild_id=$1 AND name=$2', inter.guild.id, nome.lower().strip())
        if not row:
            return await reply(inter, 'Tag não encontrada.')
        await reply(inter, clip(row['content'], 1900))

    @group_1.command(name='tag_lista', description='Lista tags disponíveis.')
    async def tag_list(self, inter):
        rows = await self.pool.fetch('SELECT name,owner_id,updated_at FROM nexus_tags WHERE guild_id=$1 ORDER BY name LIMIT 40', inter.guild.id)
        e = embed('🏷️ NEXUS • TAGS', f'{len(rows)} tags')
        for r in rows:
            e.add_field(name=r['name'], value=f"Criador: <@{r['owner_id']}> • <t:{int(r['updated_at'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='tag_remover', description='Remove tag (criador ou staff).')
    async def tag_remove(self, inter, nome: str):
        row = await self.pool.fetchrow('SELECT owner_id FROM nexus_tags WHERE guild_id=$1 AND name=$2', inter.guild.id, nome.lower().strip())
        if not row:
            return await reply(inter, 'Tag não encontrada.')
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if row['owner_id'] != inter.user.id and (not staff(inter.user, cfg)):
            return await reply(inter, 'Somente criador ou staff pode remover.')
        await self.pool.execute('DELETE FROM nexus_tags WHERE guild_id=$1 AND name=$2', inter.guild.id, nome.lower().strip())
        await reply(inter, 'Tag removida.')

    @group_1.command(name='starboard_config', description='Configura canal de mensagens em destaque (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def starboard_config(self, inter, canal: discord.TextChannel, limite: app_commands.Range[int, 1, 25]=3, emoji: str='⭐'):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'starboard_channel_id', canal.id)
        await core.setcfg(inter.guild.id, 'starboard_threshold', limite)
        await core.setcfg(inter.guild.id, 'starboard_emoji', emoji)
        await reply(inter, f'⭐ Starboard configurado em {canal.mention}; limite **{limite}** reações {emoji}.')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        g = self.bot.get_guild(payload.guild_id)
        if not g:
            return
        cfg = await self.bot.get_cog('Systems').config(g.id)
        if not cfg.get('starboard_channel_id') or str(payload.emoji) != str(cfg.get('starboard_emoji', '⭐')):
            return
        try:
            src = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        except (discord.HTTPException, AttributeError):
            return
        if src.author.bot or src.channel.id == cfg.get('starboard_channel_id'):
            return
        count = 0
        for reaction in src.reactions:
            if str(reaction.emoji) == str(payload.emoji):
                count = reaction.count
                break
        if count < int(cfg.get('starboard_threshold', 3)):
            return
        board = g.get_channel(cfg['starboard_channel_id'])
        if not board:
            return
        row = await self.pool.fetchrow('SELECT board_message_id FROM nexus_starboard WHERE guild_id=$1 AND source_message_id=$2', g.id, src.id)
        e = embed('⭐ MENSAGEM EM DESTAQUE', clip(src.content or '(mensagem sem texto)', 3000))
        e.add_field(name='Autor', value=src.author.mention, inline=True)
        e.add_field(name='Canal', value=src.channel.mention, inline=True)
        e.add_field(name='Reações', value=f'{payload.emoji} {count}', inline=True)
        e.add_field(name='Original', value=f'[Abrir mensagem]({src.jump_url})', inline=False)
        if src.attachments:
            e.set_image(url=src.attachments[0].url)
        try:
            if row:
                post = await board.fetch_message(row['board_message_id'])
                await post.edit(embed=e)
            else:
                post = await board.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
                await self.pool.execute('INSERT INTO nexus_starboard(guild_id,source_message_id,board_message_id,source_channel_id) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,source_message_id) DO UPDATE SET board_message_id=EXCLUDED.board_message_id', g.id, src.id, post.id, src.channel.id)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.guild_id is None:
            return
        g = self.bot.get_guild(payload.guild_id)
        if not g:
            return
        cfg = await self.bot.get_cog('Systems').config(g.id)
        if str(payload.emoji) != str(cfg.get('starboard_emoji', '⭐')):
            return
        try:
            src = await g.get_channel(payload.channel_id).fetch_message(payload.message_id)
        except (discord.HTTPException, AttributeError):
            return
        count = next((r.count for r in src.reactions if str(r.emoji) == str(payload.emoji)), 0)
        row = await self.pool.fetchrow('SELECT board_message_id FROM nexus_starboard WHERE guild_id=$1 AND source_message_id=$2', g.id, src.id)
        if not row:
            return
        board = g.get_channel(cfg.get('starboard_channel_id'))
        if count < int(cfg.get('starboard_threshold', 3)):
            try:
                post = await board.fetch_message(row['board_message_id'])
                await post.delete()
            except discord.HTTPException:
                pass
            await self.pool.execute('DELETE FROM nexus_starboard WHERE guild_id=$1 AND source_message_id=$2', g.id, src.id)

    @group_1.command(name='starboard_limpar', description='Remove mensagem destacada por ID original (staff).')
    async def starboard_remove(self, inter, mensagem_id: str):
        if not await self.staff_gate(inter):
            return
        if not mensagem_id.isdigit():
            return await reply(inter, 'ID inválido.')
        row = await self.pool.fetchrow('SELECT board_message_id FROM nexus_starboard WHERE guild_id=$1 AND source_message_id=$2', inter.guild.id, int(mensagem_id))
        if not row:
            return await reply(inter, 'Registro não encontrado.')
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        board = inter.guild.get_channel(cfg.get('starboard_channel_id'))
        if board:
            try:
                post = await board.fetch_message(row['board_message_id'])
                await post.delete()
            except discord.HTTPException:
                pass
        await self.pool.execute('DELETE FROM nexus_starboard WHERE guild_id=$1 AND source_message_id=$2', inter.guild.id, int(mensagem_id))
        await reply(inter, 'Destaque removido.')

    @group_1.command(name='nivel_cargo_config', description='Configura cargo concedido ao atingir nível (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def level_role_config(self, inter, nivel: app_commands.Range[int, 1, 500], cargo: discord.Role):
        await self.pool.execute('INSERT INTO nexus_level_rewards(guild_id,level,role_id) VALUES($1,$2,$3) ON CONFLICT(guild_id,level) DO UPDATE SET role_id=EXCLUDED.role_id', inter.guild.id, nivel, cargo.id)
        await reply(inter, f'✨ Cargo {cargo.mention} configurado para nível **{nivel}**.')

    @group_1.command(name='nivel_cargo_remover', description='Remove recompensa de cargo por nível.')
    @app_commands.checks.has_permissions(administrator=True)
    async def level_role_remove(self, inter, nivel: int):
        res = await self.pool.execute('DELETE FROM nexus_level_rewards WHERE guild_id=$1 AND level=$2', inter.guild.id, nivel)
        await reply(inter, 'Recompensa removida.' if res.endswith('1') else 'Nível não configurado.')

    @group_1.command(name='nivel_cargos', description='Lista recompensas de cargo por nível.')
    async def level_role_list(self, inter):
        rows = await self.pool.fetch('SELECT level,role_id FROM nexus_level_rewards WHERE guild_id=$1 ORDER BY level', inter.guild.id)
        e = embed('✨ NEXUS • RECOMPENSAS DE NÍVEL', f'{len(rows)} recompensas')
        for r in rows:
            e.add_field(name=f"Nível {r['level']}", value=f"<@&{r['role_id']}>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='perfil', description='Exibe perfil comunitário com XP, nível, economia e aniversário.')
    async def profile(self, inter, membro: Optional[discord.Member]=None):
        m = membro or inter.user
        xp = await self.pool.fetchrow('SELECT xp,level FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2', inter.guild.id, m.id)
        balance = await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2', inter.guild.id, m.id) or 0
        bday = await self.pool.fetchrow('SELECT month,day FROM nexus_birthdays WHERE guild_id=$1 AND user_id=$2', inter.guild.id, m.id)
        e = embed(f'🌟 PERFIL NEXUS • {m.display_name}', f"""Usuário: {m.mention}\nXP: **{(xp['xp'] if xp else 0):,}**\nNível: **{(xp['level'] if xp else 0)}**\nSaldo: **{balance:,} NXC**\nAniversário: **{(f"{bday['day']:02d}/{bday['month']:02d}" if bday else 'não cadastrado')}**""")
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='Cargo mais alto', value=m.top_role.mention, inline=True)
        e.add_field(name='Desde', value=f'<t:{int(m.joined_at.timestamp())}:R>' if m.joined_at else '—', inline=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='perfil_banner', description='Publica cartão de perfil textual no canal.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def profile_publish(self, inter, membro: discord.Member, canal: Optional[discord.TextChannel]=None):
        target = canal or inter.channel
        xp = await self.pool.fetchrow('SELECT xp,level FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        balance = await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id) or 0
        e = embed(f'🌟 MEMBRO • {membro.display_name}', f"{membro.mention}\n**XP:** {(xp['xp'] if xp else 0):,}\n**Nível:** {(xp['level'] if xp else 0)}\n**Saldo:** {balance:,} NXC")
        e.set_thumbnail(url=membro.display_avatar.url)
        await target.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, 'Perfil publicado.')

    @group_1.command(name='xp_ver', description='Consulta XP de um membro.')
    async def xp_view(self, inter, membro: Optional[discord.User]=None):
        u = membro or inter.user
        row = await self.pool.fetchrow('SELECT xp,level FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2', inter.guild.id, u.id)
        await reply(inter, f"✨ {u.mention}: **{(row['xp'] if row else 0):,} XP** • nível **{(row['level'] if row else 0)}**")

    @group_1.command(name='xp_top', description='Ranking XP com página opcional.')
    async def xp_top(self, inter, pagina: app_commands.Range[int, 1, 10]=1):
        offset = (pagina - 1) * 10
        rows = await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10 OFFSET $2', inter.guild.id, offset)
        e = embed(f'✨ NEXUS • RANKING XP (PÁGINA {pagina})', f'{len(rows)} membros')
        for i, r in enumerate(rows, offset + 1):
            e.add_field(name=f"{i}. <@{r['user_id']}>", value=f"{r['xp']:,} XP • nível {r['level']}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='config_starboard', description='Configuração resumida do starboard via slash.')
    @app_commands.checks.has_permissions(administrator=True)
    async def starboard_summary(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('starboard_channel_id')) if cfg.get('starboard_channel_id') else None
        await reply(inter, f"⭐ Canal: {(ch.mention if ch else 'não configurado')} • limite: {cfg.get('starboard_threshold', 3)} • emoji: {cfg.get('starboard_emoji', '⭐')}")

    @group_1.command(name='aniversario_privacidade', description='Informa sobre uso do registro de aniversário.')
    async def birthday_privacy(self, inter):
        await reply(inter, '🎂 O registro contém apenas dia e mês, para avisos comunitários. Você pode remover a qualquer momento com `/aniversario_remover`.')

    @group_1.command(name='tag_info', description='Ajuda rápida sobre tags personalizadas.')
    async def tag_info(self, inter):
        await reply(inter, '🏷️ Tags guardam textos reutilizáveis do servidor. Use `/tag_criar`, `/tag_ver`, `/tag_lista` e `/tag_remover`. Tags não executam código nem comandos.')

    @group_1.command(name='starboard_info', description='Explica funcionamento do sistema de destaque.')
    async def starboard_info(self, inter):
        await reply(inter, '⭐ Starboard replica mensagens que atingem o número configurado de reações. Configuração: `/starboard_config`. Mensagens do próprio bot não são republicadas. O conteúdo permanece ligado à mensagem original.')

    @group_1.command(name='aniversario_proximo', description='Mostra próximos aniversários registrados.')
    async def birthday_upcoming(self, inter):
        today = datetime.now(timezone.utc)
        rows = await self.pool.fetch('SELECT user_id,month,day FROM nexus_birthdays WHERE guild_id=$1', inter.guild.id)

        def nextday(row):
            year = today.year
            try:
                d = datetime(year, row['month'], row['day'], tzinfo=timezone.utc)
            except ValueError:
                d = datetime(year, 3, 1, tzinfo=timezone.utc)
            if d.date() < today.date():
                d = datetime(year + 1, row['month'], row['day'], tzinfo=timezone.utc)
            return d
        rows = sorted(rows, key=nextday)[:10]
        e = embed('🎂 NEXUS • PRÓXIMOS ANIVERSÁRIOS', f'{len(rows)} próximos registros')
        for r in rows:
            d = nextday(r)
            e.add_field(name=f"<@{r['user_id']}> • {r['day']:02d}/{r['month']:02d}", value=f'<t:{int(d.timestamp())}:R>', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='tag_exportar', description='Exporta tags do servidor em TXT (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def tag_export(self, inter):
        rows = await self.pool.fetch('SELECT name,content FROM nexus_tags WHERE guild_id=$1 ORDER BY name', inter.guild.id)
        text = '\n\n'.join((f"[{r['name']}]\n{r['content']}" for r in rows))
        file = discord.File(io.BytesIO(text.encode('utf-8')), filename=f'nexus_tags_{inter.guild.id}.txt')
        await inter.response.send_message(content=f'🏷️ Exportadas {len(rows)} tags.', file=file, ephemeral=True)

    @group_1.command(name='tag_importar', description='Importa tags via arquivo TXT enviado (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def tag_import(self, inter, arquivo: discord.Attachment):
        if arquivo.size > 100000:
            return await reply(inter, 'Arquivo excede 100 KB.')
        raw = (await arquivo.read()).decode('utf-8', errors='replace')
        matches = re.findall('^\\[([a-z0-9_-]{1,32})\\]\\s*\\n(.*?)(?=\\n\\n\\[[a-z0-9_-]{1,32}\\]\\s*\\n|\\Z)', raw, re.S | re.M)
        count = 0
        for name, content in matches:
            if not content.strip():
                continue
            await self.pool.execute('INSERT INTO nexus_tags(guild_id,name,content,owner_id) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,name) DO UPDATE SET content=EXCLUDED.content,owner_id=EXCLUDED.owner_id,updated_at=NOW()', inter.guild.id, name, clip(content.strip(), 1800), inter.user.id)
            count += 1
        await reply(inter, f'🏷️ {count} tags importadas/atualizadas.')

    @group_1.command(name='nexus_feedback', description='Envia feedback privado sobre o bot para o canal configurado.')
    async def feedback(self, inter, texto: str):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('suggestion_channel_id')) if cfg.get('suggestion_channel_id') else None
        if not ch:
            return await reply(inter, 'Canal de feedback não está configurado.')
        e = embed('🗣️ NEXUS • FEEDBACK', clip(texto, 1800))
        e.add_field(name='Autor', value=f'{inter.user.mention} • `{inter.user.id}`', inline=False)
        await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, 'Feedback enviado à equipe.')

    @group_2.command(name='config_starboard_reset', description='Remove configuração do starboard (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def starboard_reset(self, inter):
        core = self.bot.get_cog('Systems')
        await core.setcfg(inter.guild.id, 'starboard_channel_id', None)
        await core.setcfg(inter.guild.id, 'starboard_threshold', 3)
        await core.setcfg(inter.guild.id, 'starboard_emoji', '⭐')
        await reply(inter, 'Configuração starboard resetada. Posts existentes permanecem no canal.')

    @group_2.command(name='nexus_community_status', description='Status de tabelas dos sistemas comunitários.')
    @app_commands.checks.has_permissions(administrator=True)
    async def community_status(self, inter):
        info = []
        for label, table in [('Tags', 'nexus_tags'), ('Aniversários', 'nexus_birthdays'), ('Starboard', 'nexus_starboard'), ('Recompensas nível', 'nexus_level_rewards')]:
            try:
                count = await self.pool.fetchval(f'SELECT COUNT(*) FROM {table} WHERE guild_id=$1', inter.guild.id)
                info.append(f'✅ {label}: {count}')
            except Exception as exc:
                info.append(f'❌ {label}: {type(exc).__name__}')
        await inter.response.send_message(embed=embed('🧩 NEXUS • COMMUNITY STATUS', '\n'.join(info)), ephemeral=True)

async def _load_community(bot, pool):
    if bot.get_cog('NexusCommunity') is None:
        await bot.add_cog(NexusCommunity(bot, pool))

class NexusInteractions(commands.Cog):
    group_1 = app_commands.Group(name='interactions', description='NexusInteractions commands (interactions)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.invite_cache = {}

    async def staff_auth(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Permissão staff necessária.')
        return False

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in await guild.invites()}
            except discord.HTTPException:
                continue

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            current = {inv.code: inv.uses or 0 for inv in await member.guild.invites()}
        except discord.HTTPException:
            return
        old = self.invite_cache.get(member.guild.id, {})
        used = next((code for code, count in current.items() if count > old.get(code, 0)), None)
        self.invite_cache[member.guild.id] = current
        if not used:
            return
        try:
            inv = next((x for x in await member.guild.invites() if x.code == used))
            inviter = inv.inviter.id if inv.inviter else None
            await self.pool.execute('INSERT INTO nexus_invites(guild_id,code,uses,inviter_id) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,code) DO UPDATE SET uses=EXCLUDED.uses,inviter_id=EXCLUDED.inviter_id', member.guild.id, used, inv.uses or 0, inviter)
            if inviter:
                await self.pool.execute('INSERT INTO nexus_invite_stats(guild_id,inviter_id,joins) VALUES($1,$2,1) ON CONFLICT(guild_id,inviter_id) DO UPDATE SET joins=nexus_invite_stats.joins+1', member.guild.id, inviter)
        except (discord.HTTPException, StopIteration):
            pass

    @group_1.command(name='poll_criar', description='Cria enquete com até cinco opções e duração.')
    async def poll_create(self, inter, pergunta: str, opcao1: str, opcao2: str, opcao3: Optional[str]=None, opcao4: Optional[str]=None, opcao5: Optional[str]=None, duracao_minutos: app_commands.Range[int, 1, 10080]=1440):
        options = [x for x in [opcao1, opcao2, opcao3, opcao4, opcao5] if x]
        if len(options) < 2:
            return await reply(inter, 'Enquete precisa de ao menos duas opções.')
        due = datetime.now(timezone.utc) + timedelta(minutes=duracao_minutos)
        pid = await self.pool.fetchval('INSERT INTO nexus_polls(guild_id,channel_id,creator_id,question,options,end_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', inter.guild.id, inter.channel.id, inter.user.id, clip(pergunta, 250), options, due)
        marks = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
        e = embed(f'📊 ENQUETE NEXUS • #{pid}', f'**{clip(pergunta, 220)}**\n\n' + '\n'.join((f'{marks[i]} {clip(op, 150)}' for i, op in enumerate(options))) + f'\n\nEncerra <t:{int(due.timestamp())}:R>')
        await inter.response.send_message(embed=e)
        msg = await inter.original_response()
        await self.pool.execute('UPDATE nexus_polls SET message_id=$2 WHERE id=$1', pid, msg.id)
        for mark in marks[:len(options)]:
            try:
                await msg.add_reaction(mark)
            except discord.HTTPException:
                break

    @group_1.command(name='poll_encerrar', description='Encerra enquete e publica resultado.')
    async def poll_end(self, inter, enquete_id: int):
        row = await self.pool.fetchrow('SELECT * FROM nexus_polls WHERE guild_id=$1 AND id=$2 AND ended=FALSE', inter.guild.id, enquete_id)
        if not row:
            return await reply(inter, 'Enquete aberta não encontrada.')
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if row['creator_id'] != inter.user.id and (not staff(inter.user, cfg)):
            return await reply(inter, 'Somente criador ou staff pode encerrar.')
        ch = inter.guild.get_channel(row['channel_id'])
        try:
            msg = await ch.fetch_message(row['message_id'])
        except (discord.HTTPException, AttributeError):
            return await reply(inter, 'Mensagem original não encontrada.')
        marks = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
        results = []
        for idx, option in enumerate(row['options']):
            reaction = discord.utils.get(msg.reactions, emoji=marks[idx])
            count = max(0, (reaction.count if reaction else 0) - 1)
            results.append((option, count))
        total = sum((n for _, n in results))
        rank = sorted(results, key=lambda x: x[1], reverse=True)
        e = embed(f'📊 RESULTADO • ENQUETE #{enquete_id}', f"**{row['question']}**\nVotos contabilizados: **{total}**")
        for op, count in results:
            e.add_field(name=clip(op, 200), value=f'{count} votos • {count / total * 100:.1f}%' if total else '0 votos', inline=False)
        await ch.send(embed=e)
        await self.pool.execute('UPDATE nexus_polls SET ended=TRUE WHERE id=$1', enquete_id)
        await reply(inter, f'Enquete **#{enquete_id}** encerrada. Resultado publicado.')

    @group_1.command(name='poll_lista', description='Lista enquetes abertas neste servidor.')
    async def poll_list(self, inter):
        rows = await self.pool.fetch('SELECT id,question,end_at FROM nexus_polls WHERE guild_id=$1 AND ended=FALSE ORDER BY id DESC LIMIT 15', inter.guild.id)
        e = embed('📊 NEXUS • ENQUETES ABERTAS', f'{len(rows)} enquetes')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <t:{int(r['end_at'].timestamp())}:R>", value=r['question'], inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='candidatura_config', description='Configura canal para candidaturas de equipe.')
    @app_commands.checks.has_permissions(administrator=True)
    async def application_channel(self, inter, canal: discord.TextChannel):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'recruitment_channel_id', canal.id)
        await reply(inter, f'📨 Candidaturas serão recebidas em {canal.mention}.')

    @group_1.command(name='candidatura_enviar', description='Envia candidatura de recrutamento para análise.')
    async def application_submit(self, inter, area: str, experiencia: str, disponibilidade: str, motivacao: str):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        ch = inter.guild.get_channel(cfg.get('recruitment_channel_id')) if cfg.get('recruitment_channel_id') else None
        if not ch:
            return await reply(inter, 'Canal de candidaturas não configurado.')
        aid = await self.pool.fetchval('INSERT INTO nexus_applications(guild_id,user_id,area,experience,availability,motivation,status) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id', inter.guild.id, inter.user.id, clip(area, 100), clip(experiencia, 1200), clip(disponibilidade, 500), clip(motivacao, 1500), 'pending')
        e = embed(f'📨 CANDIDATURA NEXUS • #{aid}', f'**Candidato:** {inter.user.mention}\n**Área:** {clip(area, 100)}\n**Experiência:** {clip(experiencia, 1000)}\n**Disponibilidade:** {clip(disponibilidade, 400)}\n**Motivação:** {clip(motivacao, 1200)}')
        e.set_thumbnail(url=inter.user.display_avatar.url)
        await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, f'📨 Candidatura **#{aid}** enviada. A equipe analisará.')

    @group_1.command(name='candidatura_lista', description='Lista candidaturas recentes (staff).')
    async def application_list(self, inter, status: str='pending'):
        if not await self.staff_auth(inter):
            return
        if status not in ('pending', 'accepted', 'denied', 'all'):
            return await reply(inter, 'Status inválido.')
        rows = await self.pool.fetch('SELECT id,user_id,area,status,created_at FROM nexus_applications WHERE guild_id=$1 AND ($2=$3 OR status=$2) ORDER BY id DESC LIMIT 25', inter.guild.id, status, 'all')
        e = embed('📨 NEXUS • CANDIDATURAS', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['status']} • <@{r['user_id']}>", value=f"Área: {r['area']} • <t:{int(r['created_at'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='candidatura_decidir', description='Aceita ou recusa candidatura (staff).')
    async def application_decide(self, inter, candidatura_id: int, decisao: str, observacao: str=''):
        if not await self.staff_auth(inter):
            return
        status = decisao.lower()
        if status not in ('accepted', 'denied'):
            return await reply(inter, 'Decisão: accepted ou denied.')
        row = await self.pool.fetchrow('SELECT user_id,area FROM nexus_applications WHERE guild_id=$1 AND id=$2 AND status=$3', inter.guild.id, candidatura_id, 'pending')
        if not row:
            return await reply(inter, 'Candidatura não encontrada ou já decidida.')
        await self.pool.execute('UPDATE nexus_applications SET status=$3,reviewer_id=$4,review_note=$5,decided_at=NOW() WHERE guild_id=$1 AND id=$2', inter.guild.id, candidatura_id, status, inter.user.id, clip(observacao, 1000))
        try:
            u = await self.bot.fetch_user(row['user_id'])
            await u.send(embed=embed('📨 NEXUS • RESULTADO DA CANDIDATURA', f"Sua candidatura #{candidatura_id} para **{row['area']}** foi **{status}**.\n{clip(observacao, 600)}"))
        except discord.HTTPException:
            pass
        await reply(inter, 'Decisão registrada e candidato notificado quando DM disponível.')

    @group_1.command(name='reaction_role_config', description='Configura reação para conceder cargo (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def reaction_role_add(self, inter, canal: discord.TextChannel, mensagem_id: str, emoji: str, cargo: discord.Role):
        if not mensagem_id.isdigit():
            return await reply(inter, 'ID de mensagem inválido.')
        if cargo >= inter.guild.me.top_role:
            return await reply(inter, 'Cargo acima da hierarquia do bot.')
        try:
            message = await canal.fetch_message(int(mensagem_id))
            await message.add_reaction(emoji)
        except discord.HTTPException:
            return await reply(inter, 'Não consegui acessar mensagem ou adicionar reação.')
        await self.pool.execute('INSERT INTO nexus_reaction_roles(guild_id,channel_id,message_id,emoji,role_id) VALUES($1,$2,$3,$4,$5) ON CONFLICT(guild_id,message_id,emoji) DO UPDATE SET role_id=EXCLUDED.role_id', inter.guild.id, canal.id, int(mensagem_id), emoji, cargo.id)
        await reply(inter, f'🎭 Reação {emoji} vinculada a {cargo.mention}.')

    @group_1.command(name='reaction_role_remover', description='Remove configuração de reação/cargo.')
    @app_commands.checks.has_permissions(administrator=True)
    async def reaction_role_remove(self, inter, mensagem_id: str, emoji: str):
        if not mensagem_id.isdigit():
            return await reply(inter, 'ID inválido.')
        res = await self.pool.execute('DELETE FROM nexus_reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3', inter.guild.id, int(mensagem_id), emoji)
        await reply(inter, 'Vínculo removido.' if res.endswith('1') else 'Vínculo não encontrado.')

    @group_1.command(name='reaction_roles_lista', description='Lista vínculos de reação/cargo.')
    async def reaction_role_list(self, inter):
        rows = await self.pool.fetch('SELECT channel_id,message_id,emoji,role_id FROM nexus_reaction_roles WHERE guild_id=$1 ORDER BY message_id LIMIT 25', inter.guild.id)
        e = embed('🎭 NEXUS • REACTION ROLES', f'{len(rows)} vínculos')
        for r in rows:
            e.add_field(name=f"{r['emoji']} • <@&{r['role_id']}>", value=f"Canal: <#{r['channel_id']}>\nMensagem: `{r['message_id']}`", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        rows = await self.pool.fetch('SELECT role_id FROM nexus_reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3', payload.guild_id, payload.message_id, str(payload.emoji))
        g = self.bot.get_guild(payload.guild_id)
        member = payload.member
        if not g:
            return
        for row in rows:
            role = g.get_role(row['role_id'])
            if role and role < g.me.top_role:
                try:
                    await member.add_roles(role, reason='Nexus reaction role')
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.guild_id is None:
            return
        rows = await self.pool.fetch('SELECT role_id FROM nexus_reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3', payload.guild_id, payload.message_id, str(payload.emoji))
        g = self.bot.get_guild(payload.guild_id)
        member = g.get_member(payload.user_id) if g else None
        if not member or member.bot:
            return
        for row in rows:
            role = g.get_role(row['role_id'])
            if role:
                try:
                    await member.remove_roles(role, reason='Nexus reaction role removed')
                except discord.HTTPException:
                    pass

    async def _temp_owner(self, inter):
        row = await self.pool.fetchrow('SELECT owner_id FROM sistemas_temp_voice WHERE channel_id=$1', inter.channel.id)
        if not row:
            return await reply(inter, 'Este canal não é sala temporária Nexus.')
        if row['owner_id'] != inter.user.id and (not await self.staff_auth(inter)):
            return await reply(inter, 'Somente dono da sala ou staff pode editar.')
        return row

    @group_1.command(name='sala_renomear', description='Renomeia sua sala temporária de voz.')
    async def temp_room_rename(self, inter, nome: str):
        row = await self._temp_owner(inter)
        if not row:
            return
        await inter.channel.edit(name=clip(nome, 90), reason=f'Owner temp voice {inter.user.id}')
        await reply(inter, '🏷️ Sala renomeada.')

    @group_1.command(name='sala_limite', description='Define limite de usuários na sala temporária.')
    async def temp_room_limit(self, inter, limite: app_commands.Range[int, 0, 99]):
        row = await self._temp_owner(inter)
        if not row:
            return
        await inter.channel.edit(user_limit=limite)
        await reply(inter, f"👥 Limite configurado: {limite or 'sem limite'}.")

    @group_1.command(name='sala_trancar', description='Tranca sua sala temporária para novos usuários.')
    async def temp_room_lock(self, inter, ativar: bool=True):
        row = await self._temp_owner(inter)
        if not row:
            return
        everyone = inter.guild.default_role
        overwrite = inter.channel.overwrites_for(everyone)
        overwrite.connect = not ativar
        await inter.channel.set_permissions(everyone, overwrite=overwrite, reason='Temporary room owner setting')
        await reply(inter, f"🔒 Sala {('trancada' if ativar else 'destrancada')}.")

    @group_1.command(name='sala_transferir', description='Transfere propriedade da sala temporária.')
    async def temp_room_transfer(self, inter, novo_dono: discord.Member):
        row = await self._temp_owner(inter)
        if not row:
            return
        if not novo_dono.voice or novo_dono.voice.channel.id != inter.channel.id:
            return await reply(inter, 'Novo dono precisa estar na sua sala de voz.')
        await self.pool.execute('UPDATE sistemas_temp_voice SET owner_id=$2 WHERE channel_id=$1', inter.channel.id, novo_dono.id)
        await reply(inter, f'👑 Dono da sala transferido para {novo_dono.mention}.')

    @group_1.command(name='sala_deletar', description='Deleta sua sala temporária.')
    async def temp_room_delete(self, inter):
        row = await self._temp_owner(inter)
        if not row:
            return
        ch = inter.channel
        await self.pool.execute('DELETE FROM sistemas_temp_voice WHERE channel_id=$1', ch.id)
        await ch.delete(reason=f'Temporary room owner {inter.user.id}')
        await reply(inter, 'Sala temporária removida.')

    @group_1.command(name='convites_top', description='Ranking de convites contabilizados (staff).')
    async def invite_top(self, inter):
        rows = await self.pool.fetch('SELECT inviter_id,joins FROM nexus_invite_stats WHERE guild_id=$1 ORDER BY joins DESC LIMIT 15', inter.guild.id)
        e = embed('📨 NEXUS • RANKING DE CONVITES', f'{len(rows)} registros')
        for i, r in enumerate(rows, 1):
            e.add_field(name=f"{i}. <@{r['inviter_id']}>", value=f"{r['joins']} entradas atribuídas", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='convites_usuario', description='Consulta convites atribuídos a um usuário.')
    async def invite_user(self, inter, usuario: discord.User):
        count = await self.pool.fetchval('SELECT joins FROM nexus_invite_stats WHERE guild_id=$1 AND inviter_id=$2', inter.guild.id, usuario.id) or 0
        await reply(inter, f'📨 {usuario.mention}: **{count}** entradas atribuídas via convites monitorados.')

    @group_1.command(name='candidatura_info', description='Informa o fluxo de candidatura Nexus.')
    async def application_info(self, inter):
        await reply(inter, '📨 Candidatura: `/candidatura_enviar` preenche área, experiência, disponibilidade e motivação. A equipe analisa no canal configurado e decide por `/candidatura_decidir`.')

    @group_1.command(name='reaction_role_info', description='Ajuda sobre reação e cargos automáticos.')
    async def reaction_role_info(self, inter):
        await reply(inter, '🎭 Reaction roles: admin vincula mensagem/emoji/cargo com `/reaction_role_config`. Adicionar reação concede cargo; remover reação revoga. Bot deve ter Manage Roles e hierarquia acima dos cargos vinculados.')

    @group_1.command(name='poll_info', description='Ajuda do sistema de enquetes persistentes.')
    async def poll_info(self, inter):
        await reply(inter, '📊 Enquetes: `/poll_criar` cria com prazo, `/poll_lista` mostra abertas e `/poll_encerrar` publica contagem. A reação do bot é excluída da contagem.')

    @group_1.command(name='nexus_interactions_status', description='Diagnóstico de enquetes, candidaturas e reaction roles.')
    @app_commands.checks.has_permissions(administrator=True)
    async def interactions_status(self, inter):
        details = []
        for label, table in [('Enquetes', 'nexus_polls'), ('Candidaturas', 'nexus_applications'), ('Reaction roles', 'nexus_reaction_roles'), ('Convites', 'nexus_invite_stats')]:
            try:
                n = await self.pool.fetchval(f'SELECT COUNT(*) FROM {table} WHERE guild_id=$1', inter.guild.id)
                details.append(f'✅ {label}: {n}')
            except Exception as ex:
                details.append(f'⚠️ {label}: {type(ex).__name__}')
        await inter.response.send_message(embed=embed('🧩 NEXUS • INTERACTIONS STATUS', '\n'.join(details)), ephemeral=True)

async def _load_interactions(bot, pool):
    if bot.get_cog('NexusInteractions') is None:
        await bot.add_cog(NexusInteractions(bot, pool))

class NexusVirtualEconomy(commands.Cog):
    group_1 = app_commands.Group(name='items', description='NexusVirtualEconomy commands (items)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_check(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Somente staff pode administrar catálogo de itens.')
        return False

    @group_1.command(name='item_criar', description='Cria item virtual no catálogo (staff).')
    async def item_create(self, inter, nome: str, descricao: str, preco_nxc: app_commands.Range[int, 1, 100000000], quantidade: app_commands.Range[int, 0, 1000000]=0, consumivel: bool=True):
        if not await self.staff_check(inter):
            return
        iid = await self.pool.fetchval('INSERT INTO nexus_virtual_items(guild_id,name,description,price,stock,consumable,active) VALUES($1,$2,$3,$4,$5,$6,TRUE) RETURNING id', inter.guild.id, clip(nome, 100), clip(descricao, 900), preco_nxc, quantidade, consumivel)
        await reply(inter, f'🎁 Item **#{iid}** criado: **{nome}** • {preco_nxc:,} NXC.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Item virtual criado', {'item': iid, 'name': nome, 'price': preco_nxc, 'stock': quantidade})

    @group_1.command(name='item_remover', description='Desativa item virtual (staff).')
    async def item_remove(self, inter, item_id: int):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute('UPDATE nexus_virtual_items SET active=FALSE WHERE guild_id=$1 AND id=$2', inter.guild.id, item_id)
        await reply(inter, 'Item desativado.' if res.endswith('1') else 'Item não encontrado.')

    @group_1.command(name='item_catalogo', description='Lista itens virtuais disponíveis.')
    async def item_catalog(self, inter):
        rows = await self.pool.fetch('SELECT id,name,description,price,stock,consumable FROM nexus_virtual_items WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 25', inter.guild.id)
        e = embed('🎁 NEXUS • CATÁLOGO DE ITENS', f'{len(rows)} itens')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['name']} • {r['price']:,} NXC", value=f"{clip(r['description'], 300)}\nEstoque: {r['stock']} • {('Consumível' if r['consumable'] else 'Permanente')}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='item_comprar', description='Compra item virtual com NXC.')
    async def item_buy(self, inter, item_id: int, quantidade: app_commands.Range[int, 1, 25]=1):
        gid, uid = (inter.guild.id, inter.user.id)
        core = self.bot.get_cog('Systems')
        await core.ensure_wallet(gid, uid)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock($1)', uid)
                item = await conn.fetchrow('SELECT * FROM nexus_virtual_items WHERE guild_id=$1 AND id=$2 AND active=TRUE FOR UPDATE', gid, item_id)
                if not item:
                    return await reply(inter, 'Item não encontrado.')
                if item['stock'] < quantidade:
                    return await reply(inter, 'Estoque insuficiente.')
                total = item['price'] * quantidade
                balance = await conn.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE', gid, uid)
                if balance < total:
                    return await reply(inter, f'Saldo insuficiente. Custo: {total:,} NXC.')
                await conn.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2', gid, uid, total)
                await conn.execute('UPDATE nexus_virtual_items SET stock=stock-$2 WHERE guild_id=$1 AND id=$3', gid, quantidade, item_id)
                await conn.execute('INSERT INTO nexus_inventory(guild_id,user_id,item_id,quantity) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=nexus_inventory.quantity+$4', gid, uid, item_id, quantidade)
                await conn.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,NULL,$3,$4)', gid, uid, total, 'item_purchase')
        await reply(inter, f"🛒 Compra concluída: **{quantidade}x {item['name']}** por **{total:,} NXC**. Confira `/inventario`.")
        await core.audit(inter.guild, inter.user.id, 'Item comprado', {'item': item_id, 'qty': quantidade, 'total': total})

    @group_1.command(name='inventario', description='Consulta seu inventário de itens virtuais.')
    async def inventory(self, inter, membro: Optional[discord.User]=None):
        user = membro or inter.user
        if user.id != inter.user.id and (not await self.staff_check(inter)):
            return
        rows = await self.pool.fetch('SELECT i.item_id,i.quantity,v.name,v.description,v.consumable FROM nexus_inventory i JOIN nexus_virtual_items v ON v.id=i.item_id WHERE i.guild_id=$1 AND i.user_id=$2 ORDER BY v.name', inter.guild.id, user.id)
        e = embed(f'🎒 NEXUS • INVENTÁRIO DE {user.display_name}', f'{len(rows)} tipos de item')
        for r in rows:
            e.add_field(name=f"{r['name']} × {r['quantity']}", value=f"ID: `{r['item_id']}` • {('Consumível' if r['consumable'] else 'Permanente')}\n{clip(r['description'], 250)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='item_usar', description='Consome um item de inventário quando configurado como consumível.')
    async def item_use(self, inter, item_id: int, quantidade: app_commands.Range[int, 1, 10]=1):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow('SELECT i.quantity,v.name,v.consumable,v.active FROM nexus_inventory i JOIN nexus_virtual_items v ON v.id=i.item_id WHERE i.guild_id=$1 AND i.user_id=$2 AND i.item_id=$3 FOR UPDATE', inter.guild.id, inter.user.id, item_id)
                if not row:
                    return await reply(inter, 'Você não possui este item.')
                if not row['active']:
                    return await reply(inter, 'Este item está desativado.')
                if not row['consumable']:
                    return await reply(inter, 'Este item é permanente; não pode ser consumido.')
                if row['quantity'] < quantidade:
                    return await reply(inter, 'Quantidade insuficiente no inventário.')
                await conn.execute('UPDATE nexus_inventory SET quantity=quantity-$4 WHERE guild_id=$1 AND user_id=$2 AND item_id=$3', inter.guild.id, inter.user.id, item_id, quantidade)
                await conn.execute('DELETE FROM nexus_inventory WHERE guild_id=$1 AND user_id=$2 AND item_id=$3 AND quantity<=0', inter.guild.id, inter.user.id, item_id)
        await reply(inter, f"🎁 Item **{row['name']}** consumido ×{quantidade}. O item é cosmético/virtual; nenhum benefício externo foi aplicado.")

    @group_1.command(name='cupom_criar', description='Cria cupom de desconto para loja virtual (staff).')
    async def coupon_create(self, inter, codigo: str, desconto_percentual: app_commands.Range[int, 1, 90], validade_horas: app_commands.Range[int, 1, 8760]=24):
        if not await self.staff_check(inter):
            return
        code = codigo.upper().strip()
        if not re.fullmatch('[A-Z0-9_-]{3,24}', code):
            return await reply(inter, 'Código inválido (3–24 caracteres, letras/números/hífen/underscore).')
        expires = datetime.now(timezone.utc) + timedelta(hours=validade_horas)
        await self.pool.execute('INSERT INTO nexus_coupons(guild_id,code,discount_percent,active,expires_at) VALUES($1,$2,$3,TRUE,$4) ON CONFLICT(guild_id,code) DO UPDATE SET discount_percent=EXCLUDED.discount_percent,active=TRUE,expires_at=EXCLUDED.expires_at', inter.guild.id, code, desconto_percentual, expires)
        await reply(inter, f'🏷️ Cupom **{code}** criado: **{desconto_percentual}%** até <t:{int(expires.timestamp())}:R>.')

    @group_1.command(name='cupom_remover', description='Desativa cupom de desconto (staff).')
    async def coupon_remove(self, inter, codigo: str):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute('UPDATE nexus_coupons SET active=FALSE WHERE guild_id=$1 AND code=$2', inter.guild.id, codigo.upper().strip())
        await reply(inter, 'Cupom desativado.' if res.endswith('1') else 'Cupom não encontrado.')

    @group_1.command(name='cupom_lista', description='Lista cupons ativos (staff).')
    async def coupon_list(self, inter):
        if not await self.staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT code,discount_percent,expires_at FROM nexus_coupons WHERE guild_id=$1 AND active=TRUE ORDER BY code', inter.guild.id)
        e = embed('🏷️ NEXUS • CUPONS', f'{len(rows)} cupons ativos')
        for r in rows:
            e.add_field(name=f"{r['code']} • {r['discount_percent']}%", value=f"Expira: <t:{int(r['expires_at'].timestamp())}:R>" if r['expires_at'] else 'Sem expiração', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='cupom_validar', description='Valida cupom sem aplicá-lo a compra.')
    async def coupon_validate(self, inter, codigo: str):
        row = await self.pool.fetchrow('SELECT discount_percent,expires_at FROM nexus_coupons WHERE guild_id=$1 AND code=$2 AND active=TRUE', inter.guild.id, codigo.upper().strip())
        if not row:
            return await reply(inter, 'Cupom inexistente ou desativado.')
        if row['expires_at'] and row['expires_at'] <= datetime.now(timezone.utc):
            return await reply(inter, 'Cupom expirado.')
        await reply(inter, f"🏷️ Cupom válido: **{row['discount_percent']}%**. Observação: desconto em compra de moeda real não é processado; cupom é cadastro interno.")

    @group_1.command(name='economia_faq', description='Explica regras básicas da economia NXC.')
    async def economy_faq(self, inter):
        e = embed('💰 NEXUS • ECONOMIA', 'NXC é saldo virtual de comunidade. Ganhe com daily/work, transfira entre membros, compre itens e produtos cadastrados.\n\n**Não é dinheiro real.** Não há conversão, saque ou pagamento externo. Staff pode ajustar saldo e deve registrar justificativa. Compras virtuais são registradas em ledger.')
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='economia_saldo_reset', description='Zera saldo virtual de membro (staff).')
    async def balance_reset(self, inter, membro: discord.User, motivo: str):
        if not await self.staff_check(inter):
            return
        await self.pool.execute('UPDATE nexus_wallets SET balance=0 WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        await self.pool.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,amount,kind) VALUES($1,$2,0,$3)', inter.guild.id, membro.id, 'admin_reset')
        await reply(inter, f'Saldo de {membro.mention} zerado.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Economia: saldo zerado', {'user': membro.id, 'reason': motivo})

    @group_1.command(name='economia_saldo_set', description='Define saldo virtual exatamente (staff).')
    async def balance_set(self, inter, membro: discord.User, valor: app_commands.Range[int, 0, 100000000], motivo: str):
        if not await self.staff_check(inter):
            return
        core = self.bot.get_cog('Systems')
        await core.ensure_wallet(inter.guild.id, membro.id)
        old = await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id) or 0
        await self.pool.execute('UPDATE nexus_wallets SET balance=$3 WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id, valor)
        await self.pool.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,amount,kind) VALUES($1,$2,$3,$4)', inter.guild.id, membro.id, abs(valor - old), 'admin_set')
        await reply(inter, f'Saldo definido para **{valor:,} NXC**.')
        await core.audit(inter.guild, inter.user.id, 'Economia: saldo definido', {'user': membro.id, 'old': old, 'new': valor, 'reason': motivo})

    @group_1.command(name='item_transferir', description='Transfere item de inventário a outro membro.')
    async def item_transfer(self, inter, destino: discord.User, item_id: int, quantidade: app_commands.Range[int, 1, 20]):
        if destino.id == inter.user.id or destino.bot:
            return await reply(inter, 'Destino inválido.')
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                source = await conn.fetchrow('SELECT quantity FROM nexus_inventory WHERE guild_id=$1 AND user_id=$2 AND item_id=$3 FOR UPDATE', inter.guild.id, inter.user.id, item_id)
                if not source or source['quantity'] < quantidade:
                    return await reply(inter, 'Quantidade insuficiente.')
                await conn.execute('UPDATE nexus_inventory SET quantity=quantity-$4 WHERE guild_id=$1 AND user_id=$2 AND item_id=$3', inter.guild.id, inter.user.id, item_id, quantidade)
                await conn.execute('INSERT INTO nexus_inventory(guild_id,user_id,item_id,quantity) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=nexus_inventory.quantity+$4', inter.guild.id, destino.id, item_id, quantidade)
                await conn.execute('DELETE FROM nexus_inventory WHERE guild_id=$1 AND user_id=$2 AND item_id=$3 AND quantity<=0', inter.guild.id, inter.user.id, item_id)
        await reply(inter, f'🎁 Transferidos **{quantidade}** itens para {destino.mention}.')

    @group_1.command(name='economia_transacoes', description='Lista transações recentes (staff).')
    async def economy_transactions(self, inter, limite: app_commands.Range[int, 1, 30]=15):
        if not await self.staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT id,from_user,to_user,amount,kind,created_at FROM nexus_economy_tx WHERE guild_id=$1 ORDER BY id DESC LIMIT $2', inter.guild.id, limite)
        e = embed('💳 NEXUS • TRANSAÇÕES', f'{len(rows)} registros recentes')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['kind']} • {r['amount']:,} NXC", value=f"<t:{int(r['created_at'].timestamp())}:R>\nOrigem <@{r['from_user'] or 0}> → destino <@{r['to_user'] or 0}>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='economia_config_limite', description='Define limite máximo de transferência NXC (configuração).')
    @app_commands.checks.has_permissions(administrator=True)
    async def transfer_limit_config(self, inter, limite: app_commands.Range[int, 1, 100000000]):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'economy_transfer_limit', limite)
        await reply(inter, f'⚙️ Limite configurado: {limite:,} NXC por transferência. O limite é configuração para uso em fluxos futuros.')

    @group_1.command(name='nexus_virtual_status', description='Diagnóstico de catálogo, itens, inventários e cupons.')
    @app_commands.checks.has_permissions(administrator=True)
    async def virtual_status(self, inter):
        out = []
        for label, table in [('Produtos', 'nexus_products'), ('Pedidos', 'nexus_orders'), ('Itens', 'nexus_virtual_items'), ('Inventários', 'nexus_inventory'), ('Cupons', 'nexus_coupons')]:
            try:
                n = await self.pool.fetchval(f'SELECT COUNT(*) FROM {table} WHERE guild_id=$1', inter.guild.id)
                out.append(f'• {label}: {n}')
            except Exception as ex:
                out.append(f'• {label}: {type(ex).__name__}')
        await inter.response.send_message(embed=embed('🎁 NEXUS • VIRTUAL ECONOMY', '\n'.join(out)), ephemeral=True)

async def _load_virtual_economy(bot, pool):
    if bot.get_cog('NexusVirtualEconomy') is None:
        await bot.add_cog(NexusVirtualEconomy(bot, pool))

class NexusSecurity(commands.Cog):
    group_1 = app_commands.Group(name='security', description='NexusSecurity commands (security)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_gate(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff necessária.')
        return False

    async def cog_load(self):
        self.bot.add_view(NexusVerifyView())

    @group_1.command(name='verificacao_config', description='Configura cargo e publica painel de verificação.')
    @app_commands.checks.has_permissions(administrator=True)
    async def verification_config(self, inter, cargo: discord.Role, canal: discord.TextChannel, descricao: str='Clique no botão abaixo para confirmar que leu as instruções.'):
        if cargo >= inter.guild.me.top_role:
            return await reply(inter, 'Cargo de verificação precisa estar abaixo do cargo do bot.')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'verification_role_id', cargo.id)
        e = embed('🛡️ NEXUS • VERIFICAÇÃO', clip(descricao, 1800))
        e.add_field(name='Confirmação', value='Clique em **Verificar** para receber o cargo de acesso.', inline=False)
        await canal.send(embed=e, view=NexusVerifyView(), allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, f'Painel publicado em {canal.mention}; cargo {cargo.mention}.')

    @group_1.command(name='verificacao_remover', description='Remove cargo de verificação do membro (staff).')
    async def verification_remove(self, inter, membro: discord.Member):
        if not await self.staff_gate(inter):
            return
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        role = inter.guild.get_role(cfg.get('verification_role_id')) if cfg.get('verification_role_id') else None
        if not role or role not in membro.roles:
            return await reply(inter, 'Membro não possui cargo de verificação configurado.')
        await membro.remove_roles(role, reason=f'Removido por {inter.user.id}')
        await reply(inter, f'Cargo de verificação removido de {membro.mention}.')

    @group_1.command(name='verificacao_status', description='Consulta cargo e painel configurado.')
    @app_commands.checks.has_permissions(administrator=True)
    async def verification_status(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        role = inter.guild.get_role(cfg.get('verification_role_id')) if cfg.get('verification_role_id') else None
        await reply(inter, f"🛡️ Cargo configurado: {(role.mention if role else 'não configurado')}.")

    @group_1.command(name='servidor_lockdown', description='Aplica lockdown temporário aos canais (staff/admin).')
    async def lockdown(self, inter, escopo: str='text', motivo: str='Lockdown de segurança'):
        if not await self.staff_gate(inter):
            return
        scope = escopo.lower()
        if scope not in ('text', 'voice', 'all'):
            return await reply(inter, 'Escopo: text, voice ou all.')
        await inter.response.defer(ephemeral=True)
        channels = [c for c in inter.guild.channels if scope == 'all' or (scope == 'text' and isinstance(c, discord.TextChannel)) or (scope == 'voice' and isinstance(c, (discord.VoiceChannel, discord.StageChannel)))]
        staff_cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        staffroles = set(staff_cfg.get('staff_role_ids') or [])
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval('SELECT 1 FROM nexus_lockdown WHERE guild_id=$1 AND active=TRUE', inter.guild.id)
                if existing:
                    return await inter.followup.send('Lockdown já está ativo. Use `/servidor_lockdown_sair` para restaurar.', ephemeral=True)
                await conn.execute('INSERT INTO nexus_lockdown(guild_id,actor_id,scope,reason,active) VALUES($1,$2,$3,$4,TRUE)', inter.guild.id, inter.user.id, scope, clip(motivo, 500))
                for ch in channels:
                    everyone = ch.overwrites_for(inter.guild.default_role)
                    snap = {'everyone_send': everyone.send_messages, 'everyone_connect': everyone.connect, 'staff': {}}
                    for rid in staffroles:
                        role = inter.guild.get_role(rid)
                        if role:
                            ow = ch.overwrites_for(role)
                            snap['staff'][str(rid)] = {'send': ow.send_messages, 'connect': ow.connect}
                    await conn.execute('INSERT INTO nexus_lockdown_overwrites(guild_id,channel_id,snapshot) VALUES($1,$2,$3::jsonb)', inter.guild.id, ch.id, json.dumps(snap))
                    everyone.send_messages = False if isinstance(ch, discord.TextChannel) else everyone.send_messages
                    everyone.connect = False if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)) else everyone.connect
                    await ch.set_permissions(inter.guild.default_role, overwrite=everyone, reason=f'Lockdown por {inter.user.id}: {motivo}')
                    for rid in staffroles:
                        role = inter.guild.get_role(rid)
                        if role:
                            staffow = ch.overwrites_for(role)
                            if isinstance(ch, discord.TextChannel):
                                staffow.send_messages = True
                            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                                staffow.connect = True
                            await ch.set_permissions(role, overwrite=staffow, reason='Nexus lockdown staff override')
        await inter.followup.send(f'🚨 Lockdown **{scope}** aplicado em **{len(channels)}** canais. Staff autorizada mantém acesso. Motivo: {clip(motivo, 400)}. Use `/servidor_lockdown_sair` para restaurar overwrites.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Lockdown aplicado', {'scope': scope, 'channels': len(channels), 'reason': motivo}, 'log_internal_channel_id', RED)

    @group_1.command(name='servidor_lockdown_sair', description='Restaura overwrites salvos antes do lockdown.')
    async def lockdown_release(self, inter, motivo: str='Lockdown encerrado'):
        if not await self.staff_gate(inter):
            return
        await inter.response.defer(ephemeral=True)
        rows = await self.pool.fetch('SELECT channel_id,snapshot FROM nexus_lockdown_overwrites WHERE guild_id=$1 ORDER BY channel_id', inter.guild.id)
        restored = 0
        failed = 0
        for row in rows:
            ch = inter.guild.get_channel(row['channel_id'])
            if not ch:
                continue
            snap = row['snapshot'] if isinstance(row['snapshot'], dict) else json.loads(row['snapshot'])
            ow = ch.overwrites_for(inter.guild.default_role)
            ow.send_messages = snap.get('everyone_send')
            ow.connect = snap.get('everyone_connect')
            try:
                await ch.set_permissions(inter.guild.default_role, overwrite=ow, reason=f'Lockdown restore by {inter.user.id}: {motivo}')
                for rid, vals in snap.get('staff', {}).items():
                    role = inter.guild.get_role(int(rid))
                    if role:
                        staffow = ch.overwrites_for(role)
                        staffow.send_messages = vals.get('send')
                        staffow.connect = vals.get('connect')
                        await ch.set_permissions(role, overwrite=staffow, reason='Nexus lockdown restore')
                restored += 1
            except discord.HTTPException:
                failed += 1
        await self.pool.execute('UPDATE nexus_lockdown SET active=FALSE,ended_at=NOW(),end_actor=$2,end_reason=$3 WHERE guild_id=$1 AND active=TRUE', inter.guild.id, inter.user.id, clip(motivo, 500))
        await self.pool.execute('DELETE FROM nexus_lockdown_overwrites WHERE guild_id=$1', inter.guild.id)
        await inter.followup.send(f'🔓 Lockdown encerrado. Overwrites restaurados: **{restored}**; falhas: **{failed}**.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Lockdown encerrado', {'restored': restored, 'failed': failed, 'reason': motivo}, 'log_internal_channel_id', GREEN)

    @group_1.command(name='servidor_lockdown_status', description='Consulta status do lockdown.')
    @app_commands.checks.has_permissions(administrator=True)
    async def lockdown_status(self, inter):
        row = await self.pool.fetchrow('SELECT actor_id,scope,reason,created_at FROM nexus_lockdown WHERE guild_id=$1 AND active=TRUE ORDER BY id DESC LIMIT 1', inter.guild.id)
        if not row:
            return await reply(inter, '🔓 Lockdown não está ativo.')
        e = embed('🚨 NEXUS • LOCKDOWN ATIVO', f"Escopo: **{row['scope']}**\nAplicado por: <@{row['actor_id']}>\nMotivo: {clip(row['reason'], 500)}\nDesde: <t:{int(row['created_at'].timestamp())}:R>")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='servidor_convite', description='Cria convite temporário para o canal atual.')
    @app_commands.checks.has_permissions(create_instant_invite=True)
    async def invite_create(self, inter, usos: app_commands.Range[int, 1, 100]=1, minutos: app_commands.Range[int, 1, 10080]=60):
        invite = await inter.channel.create_invite(max_uses=usos, max_age=minutos * 60, unique=True, reason=f'Invite criado por {inter.user.id}')
        await reply(inter, f'🔗 Convite criado: {invite.url}\nUsos: {usos} • Expira em {minutos} min.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Convite criado', {'code': invite.code, 'uses': usos, 'minutes': minutos})

    @group_1.command(name='servidor_convites', description='Lista convites ativos (staff).')
    async def invite_list(self, inter):
        if not await self.staff_gate(inter):
            return
        try:
            invites = await inter.guild.invites()
        except discord.Forbidden:
            return await reply(inter, 'Bot precisa de permissão Manage Server para listar convites.')
        e = embed('🔗 NEXUS • CONVITES ATIVOS', f'{len(invites)} convites')
        for inv in invites[:25]:
            e.add_field(name=f"{inv.code} • {inv.uses or 0}/{inv.max_uses or '∞'}", value=f"Criador: {(inv.inviter.mention if inv.inviter else 'desconhecido')}\nCanal: <#{inv.channel.id}> • Expira: {(f'<t:{int(inv.expires_at.timestamp())}:R>' if inv.expires_at else 'nunca')}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='nexus_security_status', description='Diagnóstico de lockdown e verificação.')
    @app_commands.checks.has_permissions(administrator=True)
    async def security_status(self, inter):
        active = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_lockdown WHERE guild_id=$1 AND active=TRUE', inter.guild.id)
        overwrites = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_lockdown_overwrites WHERE guild_id=$1', inter.guild.id)
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        role = inter.guild.get_role(cfg.get('verification_role_id')) if cfg.get('verification_role_id') else None
        e = embed('🛡️ NEXUS • SECURITY', f"Lockdown ativo: **{active > 0}**\nSnapshots armazenados: **{overwrites}**\nCargo de verificação: {(role.mention if role else 'não configurado')}\n\nLockdown é manual; anti-raid/anti-nuke não acionam lockdown automático.")
        await inter.response.send_message(embed=e, ephemeral=True)

class NexusVerifyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Verificar', style=discord.ButtonStyle.success, emoji='✅', custom_id='nexus:verify:confirm')
    async def verify(self, inter, button):
        if not inter.guild:
            return await reply(inter, 'Use este botão em servidor.')
        cfg = await inter.client.get_cog('Systems').config(inter.guild.id)
        role = inter.guild.get_role(cfg.get('verification_role_id')) if cfg.get('verification_role_id') else None
        if not role:
            return await reply(inter, 'Cargo de verificação não configurado. Avise a administração.')
        if role in inter.user.roles:
            return await reply(inter, 'Você já está verificado.')
        if role >= inter.guild.me.top_role:
            return await reply(inter, 'Configuração inválida: cargo acima do bot.')
        try:
            await inter.user.add_roles(role, reason='Nexus verification panel')
        except discord.HTTPException:
            return await reply(inter, 'Não consegui atribuir o cargo. Confira permissões e hierarquia.')
        await reply(inter, '✅ Verificação concluída. Bem-vindo(a)!')

async def _load_security(bot, pool):
    if bot.get_cog('NexusSecurity') is None:
        await bot.add_cog(NexusSecurity(bot, pool))

class NexusWorkflow(commands.Cog):
    group_1 = app_commands.Group(name='workflow', description='NexusWorkflow commands (workflow)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_check(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Permissão de staff necessária.')
        return False

    @group_1.command(name='evento_lista', description='Lista eventos abertos e próximos.')
    async def event_list(self, inter):
        rows = await self.pool.fetch("SELECT id,title,description,channel_id,ends_at,status FROM nexus_events WHERE guild_id=$1 AND status='open' ORDER BY ends_at LIMIT 20", inter.guild.id)
        e = embed('🎉 NEXUS • EVENTOS', f'{len(rows)} eventos abertos')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {clip(r['title'], 180)}", value=f"{clip(r['description'] or '', 250)}\nCanal: <#{r['channel_id'] or 0}>\nEncerra: <t:{int(r['ends_at'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='evento_participar', description='Registra sua participação em evento aberto.')
    async def event_join(self, inter, evento_id: int):
        row = await self.pool.fetchrow('SELECT id,title,ends_at,status FROM nexus_events WHERE guild_id=$1 AND id=$2', inter.guild.id, evento_id)
        if not row or row['status'] != 'open' or row['ends_at'] < datetime.now(timezone.utc):
            return await reply(inter, 'Evento inexistente ou encerrado.')
        await self.pool.execute('INSERT INTO nexus_event_rsvps(guild_id,event_id,user_id) VALUES($1,$2,$3) ON CONFLICT(guild_id,event_id,user_id) DO NOTHING', inter.guild.id, evento_id, inter.user.id)
        count = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_event_rsvps WHERE guild_id=$1 AND event_id=$2', inter.guild.id, evento_id)
        await reply(inter, f"🎉 Você confirmou presença em **{row['title']}**. Participantes registrados: **{count}**.")

    @group_1.command(name='evento_sair', description='Remove sua inscrição de evento.')
    async def event_leave(self, inter, evento_id: int):
        res = await self.pool.execute('DELETE FROM nexus_event_rsvps WHERE guild_id=$1 AND event_id=$2 AND user_id=$3', inter.guild.id, evento_id, inter.user.id)
        await reply(inter, 'Inscrição removida.' if res.endswith('1') else 'Você não estava inscrito.')

    @group_1.command(name='evento_participantes', description='Lista participantes registrados de evento (staff).')
    async def event_attendees(self, inter, evento_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT title FROM nexus_events WHERE guild_id=$1 AND id=$2', inter.guild.id, evento_id)
        if not row:
            return await reply(inter, 'Evento não encontrado.')
        users = await self.pool.fetch('SELECT user_id,created_at FROM nexus_event_rsvps WHERE guild_id=$1 AND event_id=$2 ORDER BY created_at LIMIT 100', inter.guild.id, evento_id)
        e = embed(f"🎉 PARTICIPANTES • {row['title']}", f'{len(users)} inscrições')
        e.description = '\n'.join((f"{i}. <@{u['user_id']}>" for i, u in enumerate(users, 1))) or 'Sem participantes.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='evento_encerrar', description='Encerra evento e registra status (staff).')
    async def event_close(self, inter, evento_id: int, resultado: str='Evento concluído'):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow("SELECT title FROM nexus_events WHERE guild_id=$1 AND id=$2 AND status='open'", inter.guild.id, evento_id)
        if not row:
            return await reply(inter, 'Evento aberto não encontrado.')
        await self.pool.execute("UPDATE nexus_events SET status='ended' WHERE guild_id=$1 AND id=$2", inter.guild.id, evento_id)
        count = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_event_rsvps WHERE guild_id=$1 AND event_id=$2', inter.guild.id, evento_id)
        await reply(inter, f'Evento **#{evento_id}** encerrado. Inscritos registrados: **{count}**. {clip(resultado, 500)}')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Evento encerrado', {'event': evento_id, 'attendees': count, 'result': resultado})

    @group_1.command(name='evento_cancelar', description='Cancela evento aberto (staff).')
    async def event_cancel(self, inter, evento_id: int, motivo: str):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute("UPDATE nexus_events SET status='cancelled' WHERE guild_id=$1 AND id=$2 AND status='open'", inter.guild.id, evento_id)
        await reply(inter, 'Evento cancelado.' if res.endswith('1') else 'Evento não encontrado ou já encerrado.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Evento cancelado', {'event': evento_id, 'reason': motivo})

    @group_1.command(name='staff_tarefa_detalhe', description='Consulta tarefa específica.')
    async def task_detail(self, inter, tarefa_id: int):
        row = await self.pool.fetchrow('SELECT * FROM nexus_staff_tasks WHERE guild_id=$1 AND id=$2', inter.guild.id, tarefa_id)
        if not row:
            return await reply(inter, 'Tarefa não encontrada.')
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg) and inter.user.id != row['assignee_id']:
            return await reply(inter, 'Sem permissão para consultar esta tarefa.')
        e = embed(f'📋 TAREFA • #{tarefa_id}', f"**{row['title']}**\n{clip(row['details'] or '', 1800)}\n\nStatus: **{row['status']}**\nResponsável: <@{row['assignee_id']}>\nCriador: <@{row['creator_id']}>\nCriada: <t:{int(row['created_at'].timestamp())}:F>")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='staff_tarefa_cancelar', description='Cancela tarefa aberta (staff).')
    async def task_cancel(self, inter, tarefa_id: int, motivo: str):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute("UPDATE nexus_staff_tasks SET status='cancelled' WHERE guild_id=$1 AND id=$2 AND status='open'", inter.guild.id, tarefa_id)
        await reply(inter, 'Tarefa cancelada.' if res.endswith('1') else 'Tarefa não encontrada ou concluída.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Staff: tarefa cancelada', {'task': tarefa_id, 'reason': motivo})

    @group_1.command(name='staff_tarefa_reatribuir', description='Reatribui tarefa aberta para outro staff.')
    async def task_reassign(self, inter, tarefa_id: int, novo_responsavel: discord.Member):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow("SELECT title,details FROM nexus_staff_tasks WHERE guild_id=$1 AND id=$2 AND status='open'", inter.guild.id, tarefa_id)
        if not row:
            return await reply(inter, 'Tarefa aberta não encontrada.')
        await self.pool.execute('UPDATE nexus_staff_tasks SET assignee_id=$3 WHERE guild_id=$1 AND id=$2', inter.guild.id, tarefa_id, novo_responsavel.id)
        try:
            await novo_responsavel.send(embed=embed(f'📋 NEXUS • TAREFA REATRIBUÍDA #{tarefa_id}', f"**{row['title']}**\n{clip(row['details'] or '', 1000)}"))
        except discord.HTTPException:
            pass
        await reply(inter, f'Tarefa **#{tarefa_id}** reatribuída para {novo_responsavel.mention}.')

    @group_1.command(name='denuncias_lista', description='Lista denúncias pendentes (staff).')
    async def report_list(self, inter, status: str='pending'):
        if not await self.staff_check(inter):
            return
        if status not in ('pending', 'accepted', 'denied', 'all'):
            return await reply(inter, 'Status inválido.')
        rows = await self.pool.fetch('SELECT id,reporter_id,target_id,reason,evidence,status,created_at FROM sistemas_reports WHERE guild_id=$1 AND ($2=$3 OR status=$2) ORDER BY id DESC LIMIT 25', inter.guild.id, status, 'all')
        e = embed('🛡️ NEXUS • DENÚNCIAS', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['status']} • alvo <@{r['target_id']}>", value=f"Denunciante: <@{r['reporter_id']}>\n{clip(r['reason'], 400)}\nProva: {clip(r['evidence'] or '—', 200)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='denuncia_decidir', description='Marca denúncia como aceita ou recusada (staff).')
    async def report_decide(self, inter, denuncia_id: int, decisao: str, nota: str=''):
        if not await self.staff_check(inter):
            return
        status = decisao.lower()
        if status not in ('accepted', 'denied'):
            return await reply(inter, 'Use accepted ou denied.')
        row = await self.pool.fetchrow('SELECT reporter_id,target_id,reason FROM sistemas_reports WHERE guild_id=$1 AND id=$2 AND status=$3', inter.guild.id, denuncia_id, 'pending')
        if not row:
            return await reply(inter, 'Denúncia pendente não encontrada.')
        await self.pool.execute('UPDATE sistemas_reports SET status=$3,reviewer_id=$4 WHERE guild_id=$1 AND id=$2', inter.guild.id, denuncia_id, status, inter.user.id)
        try:
            u = await self.bot.fetch_user(row['reporter_id'])
            await u.send(embed=embed('🛡️ NEXUS • DENÚNCIA ANALISADA', f'Denúncia **#{denuncia_id}** foi **{status}**.\n{clip(nota, 600)}'))
        except discord.HTTPException:
            pass
        await reply(inter, 'Decisão registrada.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Denúncia decidida', {'report': denuncia_id, 'status': status, 'note': nota})

    @group_1.command(name='denuncia_detalhe', description='Consulta denúncia individual (staff).')
    async def report_detail(self, inter, denuncia_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM sistemas_reports WHERE guild_id=$1 AND id=$2', inter.guild.id, denuncia_id)
        if not row:
            return await reply(inter, 'Denúncia não encontrada.')
        e = embed(f'🛡️ DENÚNCIA • #{denuncia_id}', f"Status: **{row['status']}**\nDenunciante: <@{row['reporter_id']}>\nAlvo: <@{row['target_id']}>\nMotivo: {clip(row['reason'], 1200)}\nProva: {clip(row['evidence'] or '—', 1000)}\nCriada: <t:{int(row['created_at'].timestamp())}:F>")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='solicitacoes_lista', description='Lista pedidos de punição pendentes (staff).')
    async def requests_list(self, inter, status: str='pending'):
        if not await self.staff_check(inter):
            return
        if status not in ('pending', 'approved', 'denied', 'all'):
            return await reply(inter, 'Status inválido.')
        rows = await self.pool.fetch('SELECT id,requester_id,target_id,kind,reason,status,created_at FROM sistemas_requests WHERE guild_id=$1 AND ($2=$3 OR status=$2) ORDER BY id DESC LIMIT 25', inter.guild.id, status, 'all')
        e = embed('⚖️ NEXUS • SOLICITAÇÕES', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['status']} • {r['kind']}", value=f"Solicitante <@{r['requester_id']}> • alvo <@{r['target_id']}>\n{clip(r['reason'], 500)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='solicitacao_detalhe', description='Consulta pedido de punição individual (staff).')
    async def request_detail(self, inter, solicitacao_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM sistemas_requests WHERE guild_id=$1 AND id=$2', inter.guild.id, solicitacao_id)
        if not row:
            return await reply(inter, 'Solicitação não encontrada.')
        e = embed(f'⚖️ SOLICITAÇÃO • #{solicitacao_id}', f"Status: **{row['status']}**\nSolicitante: <@{row['requester_id']}>\nAlvo: <@{row['target_id']}>\nTipo: **{row['kind']}**\nMotivo: {clip(row['reason'], 1200)}\nOcorrido: {clip(row['occurred'] or '—', 500)}\nTestemunhas: {clip(row['witnesses'] or '—', 500)}\nProvas: {clip(row['evidence_url'] or row['evidence_attachment_url'] or '—', 1000)}")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='apelacoes_lista', description='Lista apelações pendentes (staff).')
    async def appeals_list(self, inter, status: str='pending'):
        if not await self.staff_check(inter):
            return
        if status not in ('pending', 'approved', 'denied', 'all'):
            return await reply(inter, 'Status inválido.')
        rows = await self.pool.fetch('SELECT id,case_id,appellant_id,explanation,status,created_at FROM sistemas_appeals WHERE guild_id=$1 AND ($2=$3 OR status=$2) ORDER BY id DESC LIMIT 25', inter.guild.id, status, 'all')
        e = embed('📨 NEXUS • APELAÇÕES', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"#{r['id']} • caso #{r['case_id']} • {r['status']}", value=f"Usuário <@{r['appellant_id']}>\n{clip(r['explanation'], 600)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='apelacao_detalhe', description='Consulta apelação individual (staff).')
    async def appeal_detail(self, inter, appeal_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM sistemas_appeals WHERE guild_id=$1 AND id=$2', inter.guild.id, appeal_id)
        if not row:
            return await reply(inter, 'Apelação não encontrada.')
        e = embed(f'📨 APELAÇÃO • #{appeal_id}', f"Status: **{row['status']}**\nCaso: #{row['case_id']}\nUsuário: <@{row['appellant_id']}>\nExplicação: {clip(row['explanation'], 1500)}\nProvas: {clip(row['evidence'] or '—', 1000)}\nCriada: <t:{int(row['created_at'].timestamp())}:F>")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='caso_detalhe', description='Consulta caso de punição por ID.')
    async def case_detail(self, inter, caso_id: int):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        row = await self.pool.fetchrow('SELECT * FROM sistemas_cases WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        if not row:
            return await reply(inter, 'Caso não encontrado.')
        if not staff(inter.user, cfg) and inter.user.id != row['user_id']:
            return await reply(inter, 'Sem permissão para consultar este caso.')
        expiry = f"<t:{int(row['expires_at'].timestamp())}:F>" if row['expires_at'] else 'não definido'
        e = embed(f'⚖️ NEXUS • CASO #{caso_id}', f"Alvo: <@{row['user_id']}>\nModerador: <@{row['moderator_id']}>\nAção: **{row['action']}**\nMotivo: {clip(row['reason'], 1500)}\nAtivo: **{row['active']}**\nCriado: <t:{int(row['created_at'].timestamp())}:F>\nExpira: {expiry}")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='casos_usuario', description='Lista casos de punição de usuário.')
    async def cases_user(self, inter, membro: discord.User, limite: app_commands.Range[int, 1, 25]=15):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg) and inter.user.id != membro.id:
            return await reply(inter, 'Consulta de histórico restrita.')
        rows = await self.pool.fetch('SELECT id,action,reason,moderator_id,created_at,active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT $3', inter.guild.id, membro.id, limite)
        e = embed(f'⚖️ HISTÓRICO • {membro}', f'{len(rows)} casos')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['action']} • {('ativo' if r['active'] else 'inativo')}", value=f"<t:{int(r['created_at'].timestamp())}:R> • <@{r['moderator_id']}>\n{clip(r['reason'], 400)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='caso_revogar', description='Desativa registro de punição/caso (staff).')
    async def case_revoke(self, inter, caso_id: int, motivo: str):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT user_id,action FROM sistemas_cases WHERE guild_id=$1 AND id=$2 AND active=TRUE', inter.guild.id, caso_id)
        if not row:
            return await reply(inter, 'Caso ativo não encontrado.')
        await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        await reply(inter, f'Caso **#{caso_id}** marcado como inativo. (Esta ação não desfaz automaticamente ban/timeout/cargo.)')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Caso revogado', {'case_id': caso_id, 'user': row['user_id'], 'action': row['action'], 'reason': motivo})

    @group_1.command(name='nexus_workflow_status', description='Diagnóstico de eventos, tarefas, denúncias e solicitações.')
    @app_commands.checks.has_permissions(administrator=True)
    async def workflow_status(self, inter):
        results = []
        for title, table in [('Eventos', 'nexus_events'), ('Inscrições', 'nexus_event_rsvps'), ('Tarefas', 'nexus_staff_tasks'), ('Denúncias', 'sistemas_reports'), ('Solicitações', 'sistemas_requests'), ('Apelações', 'sistemas_appeals')]:
            try:
                n = await self.pool.fetchval(f'SELECT COUNT(*) FROM {table} WHERE guild_id=$1', inter.guild.id)
                results.append(f'• {title}: **{n}**')
            except Exception as ex:
                results.append(f'• {title}: ⚠️ {type(ex).__name__}')
        await inter.response.send_message(embed=embed('🧩 NEXUS • WORKFLOW', '\n'.join(results)), ephemeral=True)

async def _load_workflow(bot, pool):
    if bot.get_cog('NexusWorkflow') is None:
        await bot.add_cog(NexusWorkflow(bot, pool))

class NexusAdminTools(commands.Cog):
    group_1 = app_commands.Group(name='admin_tools', description='NexusAdminTools commands (admin_tools)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def admin_only(self, inter):
        if inter.user.guild_permissions.administrator:
            return True
        await reply(inter, '⛔ Este recurso exige Administrador.')
        return False

    @group_1.command(name='config_reset', description='Reseta uma chave específica para o padrão (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def config_reset(self, inter, chave: str):
        if chave not in DEFAULTS:
            return await reply(inter, 'Chave inválida. Consulte `/nexus_config_resumo`.')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, chave, DEFAULTS[chave])
        await reply(inter, f'⚙️ Configuração `{chave}` restaurada para padrão.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Configuração resetada', {'key': chave})

    @group_1.command(name='config_exportar', description='Exporta configurações Nexus do servidor para JSON.')
    @app_commands.checks.has_permissions(administrator=True)
    async def config_export(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        payload = {'guild_id': inter.guild.id, 'exported_at': datetime.now(timezone.utc).isoformat(), 'config': cfg}
        raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode('utf-8')
        file = discord.File(io.BytesIO(raw), filename=f'nexus_config_{inter.guild.id}.json')
        await inter.response.send_message('⚙️ Export de configuração (sem token, credenciais ou segredo de webhook).', file=file, ephemeral=True)

    @group_1.command(name='config_importar', description='Importa configuração Nexus de JSON (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def config_import(self, inter, arquivo: discord.Attachment):
        if arquivo.size > 250000:
            return await reply(inter, 'Arquivo muito grande (limite 250 KB).')
        try:
            data = json.loads((await arquivo.read()).decode('utf-8'))
            cfg = data.get('config', data)
            if not isinstance(cfg, dict):
                return await reply(inter, 'JSON precisa conter objeto `config`.')
        except Exception:
            return await reply(inter, 'Arquivo JSON inválido.')
        core = self.bot.get_cog('Systems')
        applied = []
        ignored = []
        protected = {'payment_api_key', 'payment_webhook_secret', 'remote_admin_ids', 'trusted_admin_ids'}
        for key, value in cfg.items():
            if key not in DEFAULTS or key in protected:
                ignored.append(key)
                continue
            try:
                await core.setcfg(inter.guild.id, key, value)
                applied.append(key)
            except (ValueError, TypeError):
                ignored.append(key)
        await reply(inter, f'⚙️ Importação concluída. Aplicadas: **{len(applied)}**; ignoradas: **{len(ignored)}**. IDs confiáveis e credenciais não são importados.')
        await core.audit(inter.guild, inter.user.id, 'Configuração importada', {'applied': applied, 'ignored': ignored})

    @group_1.command(name='membro_roles_backup', description='Salva cargos atuais de membro em snapshot (staff).')
    async def member_roles_backup(self, inter, membro: discord.Member):
        if not await self.admin_only(inter):
            return
        roleids = [r.id for r in membro.roles if r != inter.guild.default_role]
        sid = await self.pool.fetchval('INSERT INTO nexus_member_role_snapshots(guild_id,user_id,roles,created_by) VALUES($1,$2,$3,$4) RETURNING id', inter.guild.id, membro.id, roleids, inter.user.id)
        await reply(inter, f'🗃️ Snapshot **#{sid}** criado com **{len(roleids)}** cargos.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Snapshot de cargos criado', {'snapshot': sid, 'member': membro.id, 'roles': roleids})

    @group_1.command(name='membro_roles_restaurar', description='Restaura cargos de snapshot (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def member_roles_restore(self, inter, snapshot_id: int, membro: discord.Member):
        row = await self.pool.fetchrow('SELECT user_id,roles FROM nexus_member_role_snapshots WHERE guild_id=$1 AND id=$2', inter.guild.id, snapshot_id)
        if not row:
            return await reply(inter, 'Snapshot não encontrado.')
        if row['user_id'] != membro.id:
            return await reply(inter, 'Snapshot pertence a outro usuário.')
        roles = []
        missing = []
        blocked = []
        for rid in row['roles']:
            role = inter.guild.get_role(rid)
            if not role:
                missing.append(rid)
            elif role >= inter.guild.me.top_role:
                blocked.append(rid)
            else:
                roles.append(role)
        try:
            await membro.add_roles(*roles, reason=f'Role restore snapshot #{snapshot_id} by {inter.user.id}')
        except discord.HTTPException:
            return await reply(inter, 'Discord recusou restauração; confira hierarchy/permissions.')
        await reply(inter, f'🗃️ Snapshot restaurado. Cargos adicionados: **{len(roles)}**; ausentes: **{len(missing)}**; bloqueados por hierarquia: **{len(blocked)}**.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Snapshot de cargos restaurado', {'snapshot': snapshot_id, 'member': membro.id, 'added': len(roles), 'missing': missing, 'blocked': blocked})

    @group_1.command(name='membro_roles_snapshots', description='Lista snapshots de cargos de membro (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def member_roles_snapshots(self, inter, membro: discord.User):
        rows = await self.pool.fetch('SELECT id,created_by,created_at,roles FROM nexus_member_role_snapshots WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15', inter.guild.id, membro.id)
        e = embed(f'🗃️ NEXUS • SNAPSHOTS DE {membro}', f'{len(rows)} snapshots')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <t:{int(r['created_at'].timestamp())}:R>", value=f"Cargos salvos: {len(r['roles'])} • criador <@{r['created_by']}>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='membro_roles_snapshot_remover', description='Remove snapshot por ID (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def member_roles_snapshot_remove(self, inter, snapshot_id: int):
        res = await self.pool.execute('DELETE FROM nexus_member_role_snapshots WHERE guild_id=$1 AND id=$2', inter.guild.id, snapshot_id)
        await reply(inter, 'Snapshot apagado.' if res.endswith('1') else 'Snapshot não encontrado.')

    @group_1.command(name='auditoria_exportar', description='Exporta auditoria Nexus em CSV (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def audit_export(self, inter, limite: app_commands.Range[int, 1, 500]=250):
        rows = await self.pool.fetch('SELECT id,actor_id,action,details,created_at FROM sistemas_audit WHERE guild_id=$1 ORDER BY id DESC LIMIT $2', inter.guild.id, limite)
        out = io.StringIO()
        writer = __import__('csv').writer(out)
        writer.writerow(['id', 'actor_id', 'action', 'details', 'created_at'])
        for r in rows:
            writer.writerow([r['id'], r['actor_id'], r['action'], json.dumps(r['details'], ensure_ascii=False, default=str), r['created_at'].isoformat()])
        file = discord.File(io.BytesIO(out.getvalue().encode('utf-8-sig')), filename=f'nexus_audit_{inter.guild.id}.csv')
        await inter.response.send_message(f'📜 Exportados **{len(rows)}** registros.', file=file, ephemeral=True)

    @group_1.command(name='canal_permissoes', description='Mostra permissões sobrescritas do canal (staff).')
    async def channel_permissions(self, inter, canal: discord.abc.GuildChannel):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, 'Consulta restrita à staff.')
        lines = []
        for target, overwrite in canal.overwrites.items():
            vals = [f'{name}: {value}' for name, value in overwrite if value is not None]
            lines.append(f'**{target.name}** (`{target.id}`)\n' + (', • '.join(vals) if vals else 'Sem permissões explicitamente definidas'))
        e = embed(f'🔐 PERMISSÕES • {canal.name}', clip('\n\n'.join(lines) or 'Sem overwrites.', 3800))
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='canal_clone', description='Clona canal atual (gerenciar canais).')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_clone(self, inter, canal: discord.abc.GuildChannel, nome: Optional[str]=None):
        clone = await canal.clone(name=clip(nome or f'{canal.name}-clone', 90), reason=f'Clonado por {inter.user.id}')
        await reply(inter, f'🧬 Canal clonado: {clone.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Canal clonado', {'source': canal.id, 'clone': clone.id})

    @group_1.command(name='canal_topico', description='Atualiza tópico de canal de texto.')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_topic(self, inter, canal: discord.TextChannel, topico: str):
        await canal.edit(topic=clip(topico, 1024), reason=f'Tópico atualizado por {inter.user.id}')
        await reply(inter, f'📝 Tópico atualizado em {canal.mention}.')

    @group_1.command(name='canal_mover_categoria', description='Move canal para categoria.')
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_move_category(self, inter, canal: discord.abc.GuildChannel, categoria: Optional[discord.CategoryChannel]=None):
        await canal.edit(category=categoria, reason=f'Movido por {inter.user.id}')
        await reply(inter, f"🗂️ Canal {canal.mention} movido para {(categoria.name if categoria else 'sem categoria')}.")

    @group_1.command(name='nexus_admin_tools_status', description='Diagnóstico de snapshots e ferramentas admin.')
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_tools_status(self, inter):
        count = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_member_role_snapshots WHERE guild_id=$1', inter.guild.id)
        await inter.response.send_message(embed=embed('🧰 NEXUS • ADMIN TOOLS', f'Snapshots de cargos registrados: **{count}**\nExport/import de configuração: ativo\nExport de auditoria: ativo'), ephemeral=True)

async def _load_admin_tools(bot, pool):
    if bot.get_cog('NexusAdminTools') is None:
        await bot.add_cog(NexusAdminTools(bot, pool))

class NexusAdvanced(commands.Cog):
    group_1 = app_commands.Group(name='advanced', description='NexusAdvanced commands (advanced)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.expiration_loop.start()

    def cog_unload(self):
        self.expiration_loop.cancel()

    async def staff_permission(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff autorizada necessária.')
        return False

    @tasks.loop(minutes=1)
    async def expiration_loop(self):
        await self.bot.wait_until_ready()
        bans = await self.pool.fetch('SELECT guild_id,user_id,case_id FROM nexus_temp_bans WHERE active=TRUE AND expires_at<=NOW() ORDER BY expires_at LIMIT 50')
        for row in bans:
            guild = self.bot.get_guild(row['guild_id'])
            if not guild:
                continue
            try:
                await guild.unban(discord.Object(id=row['user_id']), reason='Nexus temporary ban expiration')
                await self.pool.execute('UPDATE nexus_temp_bans SET active=FALSE,ended_at=NOW(),end_reason=$3 WHERE guild_id=$1 AND user_id=$2', row['guild_id'], row['user_id'], 'Automatic expiration')
                await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND id=$2', row['guild_id'], row['case_id'])
            except discord.NotFound:
                await self.pool.execute('UPDATE nexus_temp_bans SET active=FALSE,ended_at=NOW(),end_reason=$3 WHERE guild_id=$1 AND user_id=$2', row['guild_id'], row['user_id'], 'User already unbanned')
            except discord.HTTPException:
                log.warning('Temporary ban expiry failed guild=%s user=%s', row['guild_id'], row['user_id'])
        roles = await self.pool.fetch('SELECT guild_id,user_id,role_id FROM nexus_temp_roles WHERE active=TRUE AND expires_at<=NOW() ORDER BY expires_at LIMIT 50')
        for row in roles:
            guild = self.bot.get_guild(row['guild_id'])
            member = guild.get_member(row['user_id']) if guild else None
            role = guild.get_role(row['role_id']) if guild else None
            try:
                if member and role:
                    await member.remove_roles(role, reason='Nexus temporary role expiration')
                await self.pool.execute('UPDATE nexus_temp_roles SET active=FALSE,ended_at=NOW() WHERE guild_id=$1 AND user_id=$2 AND role_id=$3', row['guild_id'], row['user_id'], row['role_id'])
            except discord.HTTPException:
                log.warning('Temporary role expiry failed guild=%s user=%s', row['guild_id'], row['user_id'])

    @expiration_loop.before_loop
    async def before_expiration(self):
        await self.bot.wait_until_ready()

    @group_1.command(name='ban_temporario', description='Bane usuário por prazo e agenda desbanimento.')
    @app_commands.checks.has_permissions(ban_members=True)
    async def temp_ban(self, inter, user_id: str, horas: app_commands.Range[int, 1, 8760], motivo: str):
        if not user_id.isdigit():
            return await reply(inter, 'ID de usuário inválido.')
        uid = int(user_id)
        if uid == inter.guild.owner_id or uid == inter.user.id:
            return await reply(inter, 'ID não pode ser alvo desta ação.')
        expiry = datetime.now(timezone.utc) + timedelta(hours=horas)
        try:
            await inter.guild.ban(discord.Object(id=uid), reason=f'Temp ban by {inter.user.id}: {motivo}', delete_message_seconds=0)
        except discord.HTTPException:
            return await reply(inter, 'Discord recusou banimento. Confira permissões e hierarquia.')
        core = self.bot.get_cog('Systems')
        caseid = await core.case(inter.guild.id, uid, inter.user.id, 'tempban', motivo, expiry)
        await self.pool.execute('INSERT INTO nexus_temp_bans(guild_id,user_id,case_id,expires_at,active,reason) VALUES($1,$2,$3,$4,TRUE,$5) ON CONFLICT(guild_id,user_id) DO UPDATE SET case_id=EXCLUDED.case_id,expires_at=EXCLUDED.expires_at,active=TRUE,reason=EXCLUDED.reason,created_at=NOW()', inter.guild.id, uid, caseid, expiry, clip(motivo, 1200))
        await reply(inter, f'🔨 Ban temporário aplicado ao ID `{uid}` por **{horas}h**. Expira <t:{int(expiry.timestamp())}:R>. Caso **#{caseid}**.')
        await core.audit(inter.guild, inter.user.id, 'Ban temporário aplicado', {'user_id': uid, 'hours': horas, 'expires_at': expiry.isoformat(), 'reason': motivo}, 'log_punishment_channel_id', RED)

    @group_1.command(name='ban_temporario_lista', description='Lista banimentos temporários ativos (staff).')
    async def temp_ban_list(self, inter):
        if not await self.staff_permission(inter):
            return
        rows = await self.pool.fetch('SELECT user_id,case_id,expires_at,reason FROM nexus_temp_bans WHERE guild_id=$1 AND active=TRUE ORDER BY expires_at LIMIT 25', inter.guild.id)
        e = embed('🔨 NEXUS • TEMP BANS', f'{len(rows)} banimentos temporários')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}> • caso #{r['case_id']} • <t:{int(r['expires_at'].timestamp())}:R>", value=clip(r['reason'], 350), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='ban_temporario_cancelar', description='Cancela timer de ban temporário (staff).')
    async def temp_ban_cancel(self, inter, user_id: str, desbanir: bool=False, motivo: str='Timer cancelado'):
        if not await self.staff_permission(inter):
            return
        if not user_id.isdigit():
            return await reply(inter, 'ID inválido.')
        uid = int(user_id)
        row = await self.pool.fetchrow('SELECT case_id FROM nexus_temp_bans WHERE guild_id=$1 AND user_id=$2 AND active=TRUE', inter.guild.id, uid)
        if not row:
            return await reply(inter, 'Ban temporário ativo não encontrado.')
        await self.pool.execute('UPDATE nexus_temp_bans SET active=FALSE,ended_at=NOW(),end_reason=$3 WHERE guild_id=$1 AND user_id=$2', inter.guild.id, uid, clip(motivo, 500))
        if desbanir:
            try:
                await inter.guild.unban(discord.Object(id=uid), reason=f'{inter.user.id}: {motivo}')
            except discord.NotFound:
                pass
        await reply(inter, f'Timer do ban `{uid}` cancelado. Desbanimento solicitado: **{desbanir}**.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Ban temporário cancelado', {'user_id': uid, 'unban': desbanir, 'reason': motivo}, 'log_punishment_channel_id', GREEN)

    @group_1.command(name='cargo_temporario', description='Atribui cargo por horas e remove automaticamente.')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def temp_role_add(self, inter, membro: discord.Member, cargo: discord.Role, horas: app_commands.Range[int, 1, 8760], motivo: str='Cargo temporário'):
        if cargo >= inter.guild.me.top_role:
            return await reply(inter, 'Cargo acima da hierarquia do bot.')
        expiry = datetime.now(timezone.utc) + timedelta(hours=horas)
        try:
            await membro.add_roles(cargo, reason=f'Temp role by {inter.user.id}: {motivo}')
        except discord.HTTPException:
            return await reply(inter, 'Não consegui atribuir cargo.')
        await self.pool.execute('INSERT INTO nexus_temp_roles(guild_id,user_id,role_id,expires_at,active,reason) VALUES($1,$2,$3,$4,TRUE,$5) ON CONFLICT(guild_id,user_id,role_id) DO UPDATE SET expires_at=EXCLUDED.expires_at,active=TRUE,reason=EXCLUDED.reason,created_at=NOW()', inter.guild.id, membro.id, cargo.id, expiry, clip(motivo, 500))
        await reply(inter, f'🎭 {cargo.mention} atribuído a {membro.mention} por **{horas}h**. Expira <t:{int(expiry.timestamp())}:R>.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargo temporário atribuído', {'member': membro.id, 'role': cargo.id, 'hours': horas, 'expires_at': expiry.isoformat(), 'reason': motivo})

    @group_1.command(name='cargo_temporario_lista', description='Lista cargos temporários ativos (staff).')
    async def temp_role_list(self, inter):
        if not await self.staff_permission(inter):
            return
        rows = await self.pool.fetch('SELECT user_id,role_id,expires_at,reason FROM nexus_temp_roles WHERE guild_id=$1 AND active=TRUE ORDER BY expires_at LIMIT 30', inter.guild.id)
        e = embed('🎭 NEXUS • CARGOS TEMPORÁRIOS', f'{len(rows)} registros')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}> • <@&{r['role_id']}> • <t:{int(r['expires_at'].timestamp())}:R>", value=clip(r['reason'], 250), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='cargo_temporario_cancelar', description='Cancela timer de cargo temporário.')
    async def temp_role_cancel(self, inter, membro: discord.Member, cargo: discord.Role, remover: bool=True):
        if not await self.staff_permission(inter):
            return
        res = await self.pool.execute('UPDATE nexus_temp_roles SET active=FALSE,ended_at=NOW() WHERE guild_id=$1 AND user_id=$2 AND role_id=$3 AND active=TRUE', inter.guild.id, membro.id, cargo.id)
        if not res.endswith('1'):
            return await reply(inter, 'Timer não encontrado.')
        if remover and cargo in membro.roles:
            try:
                await membro.remove_roles(cargo, reason=f'Temp role timer canceled by {inter.user.id}')
            except discord.HTTPException:
                pass
        await reply(inter, 'Timer cancelado; cargo removido conforme opção.')

    @group_1.command(name='reuniao_presenca', description='Confirma presença em reunião staff por ID.')
    async def meeting_attend(self, inter, reuniao_id: int):
        row = await self.pool.fetchrow('SELECT title,scheduled_at,status FROM nexus_staff_meetings WHERE guild_id=$1 AND id=$2', inter.guild.id, reuniao_id)
        if not row:
            return await reply(inter, 'Reunião não encontrada.')
        await self.pool.execute('INSERT INTO nexus_staff_meeting_attendance(guild_id,meeting_id,user_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING', inter.guild.id, reuniao_id, inter.user.id)
        await reply(inter, f"🗓️ Presença registrada para **{row['title']}**.")

    @group_1.command(name='reuniao_lista', description='Lista reuniões staff registradas.')
    async def meeting_list(self, inter):
        if not await self.staff_permission(inter):
            return
        rows = await self.pool.fetch('SELECT id,title,scheduled_at,status FROM nexus_staff_meetings WHERE guild_id=$1 ORDER BY scheduled_at DESC LIMIT 20', inter.guild.id)
        e = embed('🗓️ NEXUS • REUNIÕES STAFF', f'{len(rows)} reuniões')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['title']} • {r['status']}", value=f"<t:{int(r['scheduled_at'].timestamp())}:F>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='reuniao_criar', description='Cria reunião persistente e agenda no canal.')
    async def meeting_create(self, inter, canal: discord.TextChannel, titulo: str, agenda: str, data_iso_utc: str):
        if not await self.staff_permission(inter):
            return
        try:
            when = datetime.fromisoformat(data_iso_utc.replace('Z', '+00:00'))
        except ValueError:
            return await reply(inter, 'Data ISO inválida.')
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)
        mid = await self.pool.fetchval('INSERT INTO nexus_staff_meetings(guild_id,creator_id,title,agenda,channel_id,scheduled_at,status) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id', inter.guild.id, inter.user.id, clip(titulo, 180), clip(agenda, 1500), canal.id, when, 'scheduled')
        e = embed(f'🗓️ REUNIÃO STAFF • #{mid}', f'**{clip(titulo, 180)}**\n**Agenda:** {clip(agenda, 1200)}\n**Data:** <t:{int(when.timestamp())}:F>\n\nUse `/reuniao_presenca` com ID **{mid}** para confirmar presença.')
        await canal.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        await reply(inter, f'Reunião **#{mid}** criada e publicada.')

    @group_1.command(name='reuniao_presencas', description='Lista presenças registradas em reunião.')
    async def meeting_attendance_list(self, inter, reuniao_id: int):
        if not await self.staff_permission(inter):
            return
        row = await self.pool.fetchrow('SELECT title FROM nexus_staff_meetings WHERE guild_id=$1 AND id=$2', inter.guild.id, reuniao_id)
        if not row:
            return await reply(inter, 'Reunião não encontrada.')
        users = await self.pool.fetch('SELECT user_id,created_at FROM nexus_staff_meeting_attendance WHERE guild_id=$1 AND meeting_id=$2 ORDER BY created_at', inter.guild.id, reuniao_id)
        e = embed(f"🗓️ PRESENÇA • {row['title']}", f'{len(users)} confirmados')
        e.description = '\n'.join((f"{idx}. <@{r['user_id']}>" for idx, r in enumerate(users, 1))) or 'Nenhuma presença.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='reuniao_encerrar', description='Marca reunião como encerrada.')
    async def meeting_end(self, inter, reuniao_id: int, observacao: str='Concluída'):
        if not await self.staff_permission(inter):
            return
        res = await self.pool.execute("UPDATE nexus_staff_meetings SET status='ended',ended_at=NOW(),end_note=$3 WHERE guild_id=$1 AND id=$2 AND status='scheduled'", inter.guild.id, reuniao_id, clip(observacao, 800))
        await reply(inter, 'Reunião encerrada.' if res.endswith('1') else 'Reunião não encontrada ou já encerrada.')

    @group_1.command(name='nexus_advanced_status', description='Diagnóstico de bans temporários, cargos temporários e reuniões.')
    @app_commands.checks.has_permissions(administrator=True)
    async def advanced_status(self, inter):
        results = []
        for label, table in [('Temp bans', 'nexus_temp_bans'), ('Temp roles', 'nexus_temp_roles'), ('Meetings', 'nexus_staff_meetings'), ('Attendance', 'nexus_staff_meeting_attendance')]:
            try:
                count = await self.pool.fetchval(f'SELECT COUNT(*) FROM {table} WHERE guild_id=$1', inter.guild.id)
                results.append(f'{label}: **{count}**')
            except Exception as exc:
                results.append(f'{label}: {type(exc).__name__}')
        await inter.response.send_message(embed=embed('🧩 NEXUS • ADVANCED', '\n'.join(results)), ephemeral=True)

async def _load_advanced(bot, pool):
    if bot.get_cog('NexusAdvanced') is None:
        await bot.add_cog(NexusAdvanced(bot, pool))

class NexusGuildTools(commands.Cog):
    group_1 = app_commands.Group(name='guild_tools', description='NexusGuildTools commands (guild_tools)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_guard(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff autorizada necessária.')
        return False

    @group_1.command(name='automod_bypass_cargos', description='Define cargos que ignoram AutoMod (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_bypass_roles(self, inter, cargos_csv: str):
        ids = []
        for token in cargos_csv.split(','):
            token = token.strip()
            if token and token.isdigit():
                ids.append(int(token))
            elif token:
                return await reply(inter, 'Use IDs de cargos separados por vírgula.')
        ids = list(dict.fromkeys(ids))
        valid = [r.id for r in inter.guild.roles]
        invalid = [x for x in ids if x not in valid]
        if invalid:
            return await reply(inter, f'Cargos inexistentes: {invalid}')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'automod_bypass_role_ids', ids)
        await reply(inter, f'🛡️ AutoMod bypass configurado para **{len(ids)}** cargos.')

    @group_1.command(name='automod_bypass_limpar', description='Remove lista de bypass do AutoMod (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_bypass_clear(self, inter):
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'automod_bypass_role_ids', [])
        await reply(inter, 'Bypass de AutoMod removido.')

    @group_1.command(name='automod_bypass_lista', description='Lista cargos isentos do AutoMod.')
    @app_commands.checks.has_permissions(administrator=True)
    async def automod_bypass_list(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        ids = cfg.get('automod_bypass_role_ids') or []
        e = embed('🛡️ NEXUS • AUTMOD BYPASS', f'{len(ids)} cargos isentos')
        e.description = '\n'.join((f'<@&{rid}>' for rid in ids)) or 'Nenhum cargo isento.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='limpar_bots', description='Limpa mensagens de bots no canal atual.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_bots(self, inter, quantidade: app_commands.Range[int, 1, 100]):
        await inter.response.defer(ephemeral=True)
        deleted = await inter.channel.purge(limit=quantidade, check=lambda m: m.author.bot, reason=f'Bot message cleanup by {inter.user.id}')
        await inter.followup.send(f'🤖 Removidas **{len(deleted)}** mensagens de bots.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Limpeza de bots', {'channel': inter.channel.id, 'count': len(deleted)})

    @group_1.command(name='limpar_usuario', description='Limpa mensagens de membro no canal atual.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_user(self, inter, membro: discord.Member, quantidade: app_commands.Range[int, 1, 100]):
        await inter.response.defer(ephemeral=True)
        deleted = await inter.channel.purge(limit=quantidade, check=lambda m: m.author.id == membro.id, reason=f'Cleanup by {inter.user.id}')
        await inter.followup.send(f'🧹 Removidas **{len(deleted)}** mensagens de {membro.mention}.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Limpeza de usuário', {'channel': inter.channel.id, 'member': membro.id, 'count': len(deleted)})

    @group_1.command(name='limpar_links', description='Limpa mensagens que contenham links no canal.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_links(self, inter, quantidade: app_commands.Range[int, 1, 100]):
        await inter.response.defer(ephemeral=True)
        pattern = re.compile('https?://|discord\\.gg/|discord\\.com/invite/', re.I)
        deleted = await inter.channel.purge(limit=quantidade, check=lambda m: bool(pattern.search(m.content)), reason=f'Link cleanup by {inter.user.id}')
        await inter.followup.send(f'🔗 Removidas **{len(deleted)}** mensagens com links.', ephemeral=True)
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Limpeza de links', {'channel': inter.channel.id, 'count': len(deleted)})

    @group_1.command(name='limpar_embeds', description='Limpa mensagens com embeds no canal atual.')
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_embeds(self, inter, quantidade: app_commands.Range[int, 1, 100]):
        await inter.response.defer(ephemeral=True)
        deleted = await inter.channel.purge(limit=quantidade, check=lambda m: bool(m.embeds), reason=f'Embed cleanup by {inter.user.id}')
        await inter.followup.send(f'🧾 Removidas **{len(deleted)}** mensagens com embeds.', ephemeral=True)

    @group_1.command(name='discord_audit', description='Lista ações recentes do Discord audit log (staff).')
    async def discord_audit(self, inter, limite: app_commands.Range[int, 1, 25]=10):
        if not await self.staff_guard(inter):
            return
        try:
            entries = [entry async for entry in inter.guild.audit_logs(limit=limite)]
        except discord.Forbidden:
            return await reply(inter, 'Bot precisa da permissão View Audit Log.')
        e = embed('📜 NEXUS • DISCORD AUDIT LOG', f'{len(entries)} ações recentes')
        for entry in entries:
            e.add_field(name=f'{entry.action} • <t:{int(entry.created_at.timestamp())}:R>', value=f"Autor: {(entry.user.mention if entry.user else 'desconhecido')}\nAlvo: {clip(str(entry.target), 180)}\nMotivo: {clip(entry.reason or '—', 180)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='discord_audit_usuario', description='Lista ações recentes de usuário no audit log.')
    async def discord_audit_user(self, inter, membro: discord.User, limite: app_commands.Range[int, 1, 25]=10):
        if not await self.staff_guard(inter):
            return
        try:
            entries = [entry async for entry in inter.guild.audit_logs(limit=100) if entry.user and entry.user.id == membro.id][:limite]
        except discord.Forbidden:
            return await reply(inter, 'Permissão View Audit Log necessária.')
        e = embed(f'📜 AUDIT • {membro}', f'{len(entries)} ações encontradas')
        for entry in entries:
            e.add_field(name=f'{entry.action} • <t:{int(entry.created_at.timestamp())}:R>', value=f"Alvo: {clip(str(entry.target), 250)}\nMotivo: {clip(entry.reason or '—', 250)}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='discord_audit_export', description='Exporta audit log Discord para TXT (staff).')
    async def discord_audit_export(self, inter, limite: app_commands.Range[int, 1, 100]=50):
        if not await self.staff_guard(inter):
            return
        try:
            entries = [entry async for entry in inter.guild.audit_logs(limit=limite)]
        except discord.Forbidden:
            return await reply(inter, 'Permissão View Audit Log necessária.')
        text = '\n'.join((f"{entry.created_at.isoformat()} | {entry.action} | actor={(entry.user.id if entry.user else '?')} | target={entry.target} | reason={entry.reason or ''}" for entry in entries))
        file = discord.File(io.BytesIO(text.encode('utf-8')), filename=f'discord_audit_{inter.guild.id}.txt')
        await inter.response.send_message(f'📜 Exportadas {len(entries)} entradas.', file=file, ephemeral=True)

    @group_1.command(name='membros_novos', description='Lista membros mais recentes do servidor.')
    async def newest_members(self, inter, limite: app_commands.Range[int, 1, 25]=10):
        members = sorted([m for m in inter.guild.members if m.joined_at], key=lambda m: m.joined_at, reverse=True)[:limite]
        e = embed('👥 NEXUS • NOVOS MEMBROS', f'{len(members)} membros mais recentes')
        for m in members:
            e.add_field(name=m.display_name, value=f'Entrou <t:{int(m.joined_at.timestamp())}:R> • conta criada <t:{int(m.created_at.timestamp())}:R>', inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='membros_bots', description='Lista bots no servidor.')
    async def bot_members(self, inter):
        bots = [m for m in inter.guild.members if m.bot]
        e = embed('🤖 NEXUS • BOTS', f'{len(bots)} bots no cache')
        e.description = '\n'.join((f'{m.mention} • `{m.id}` • cargo {m.top_role.mention}' for m in bots[:40])) or 'Nenhum bot encontrado.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='membros_ausentes', description='Lista membros offline no cache (staff).')
    async def offline_members(self, inter, limite: app_commands.Range[int, 1, 30]=15):
        if not await self.staff_guard(inter):
            return
        members = [m for m in inter.guild.members if m.status == discord.Status.offline and (not m.bot)]
        e = embed('⚫ NEXUS • MEMBROS OFFLINE', f'{len(members)} offline no cache; exibindo até {limite}')
        e.description = '\n'.join((f'{m.display_name} • `{m.id}`' for m in members[:limite])) or 'Nenhum.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='membro_cargos_limpar', description='Remove cargos selecionados de membro (staff).')
    async def member_roles_clear(self, inter, membro: discord.Member, cargos_csv: str):
        if not await self.staff_guard(inter):
            return
        ids = []
        for x in cargos_csv.split(','):
            x = x.strip()
            if x.isdigit():
                ids.append(int(x))
            elif x:
                return await reply(inter, 'IDs de cargos separados por vírgula.')
        roles = []
        blocked = []
        missing = []
        for rid in ids:
            role = inter.guild.get_role(rid)
            if not role:
                missing.append(rid)
            elif role >= inter.guild.me.top_role or role >= inter.user.top_role:
                blocked.append(rid)
            elif role in membro.roles:
                roles.append(role)
        try:
            await membro.remove_roles(*roles, reason=f'Role cleanup by {inter.user.id}')
        except discord.HTTPException:
            return await reply(inter, 'Discord recusou remover cargos.')
        await reply(inter, f'🎭 Removidos **{len(roles)}** cargos; ausentes **{len(missing)}**; bloqueados **{len(blocked)}**.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargos removidos em lote', {'member': membro.id, 'removed': [r.id for r in roles], 'missing': missing, 'blocked': blocked})

    @group_1.command(name='membro_cargos_copiar', description='Copia cargos de um membro para outro (staff).')
    async def member_roles_copy(self, inter, origem: discord.Member, destino: discord.Member):
        if not await self.staff_guard(inter):
            return
        roles = [r for r in origem.roles if r != inter.guild.default_role and r < inter.guild.me.top_role and (r < inter.user.top_role)]
        roles = [r for r in roles if r not in destino.roles]
        try:
            await destino.add_roles(*roles, reason=f'Role copy by {inter.user.id}')
        except discord.HTTPException:
            return await reply(inter, 'Discord recusou copiar cargos.')
        await reply(inter, f'🎭 Copiados **{len(roles)}** cargos de {origem.mention} para {destino.mention}.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Cargos copiados', {'from': origem.id, 'to': destino.id, 'roles': [r.id for r in roles]})

    @group_1.command(name='cargo_membros', description='Lista membros com cargo específico.')
    async def role_members(self, inter, cargo: discord.Role, limite: app_commands.Range[int, 1, 50]=25):
        members = [m for m in cargo.members if not m.bot]
        e = embed(f'🎭 NEXUS • MEMBROS {cargo.name}', f'{len(members)} membros')
        e.description = '\n'.join((f'{m.mention} • <t:{int(m.joined_at.timestamp())}:R>' if m.joined_at else m.mention for m in members[:limite])) or 'Nenhum membro.'
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='cargo_permissoes', description='Lista permissões habilitadas de cargo.')
    async def role_permissions(self, inter, cargo: discord.Role):
        permissions = [name.replace('_', ' ').title() for name, value in cargo.permissions if value]
        e = embed(f'🔐 NEXUS • PERMISSÕES {cargo.name}', f'{len(permissions)} permissões habilitadas')
        e.description = clip('\n'.join(permissions) or 'Nenhuma permissão.', 3500)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='server_boosts', description='Lista status de boost e membros booster.')
    async def boosts_info(self, inter):
        boosters = [m for m in inter.guild.members if m.premium_since]
        e = embed('🚀 NEXUS • BOOSTS', f'Boosts: **{inter.guild.premium_subscription_count or 0}**\nNível: **{inter.guild.premium_tier}**\nBoosters em cache: **{len(boosters)}**')
        e.description = '\n'.join((f'{m.mention} • desde <t:{int(m.premium_since.timestamp())}:R>' for m in boosters[:30]))
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='servidor_contagem', description='Mostra contagem de membros, canais, cargos e emojis.')
    async def server_counts(self, inter):
        g = inter.guild
        members = g.members
        e = embed('📊 NEXUS • CONTAGEM', f'Membros cache: **{len(members)}**\nHumanos: **{sum((not m.bot for m in members))}**\nBots: **{sum((m.bot for m in members))}**\nCanais: **{len(g.channels)}**\nCategorias: **{len(g.categories)}**\nCargos: **{len(g.roles)}**\nEmojis: **{len(g.emojis)}**\nStickers: **{len(g.stickers)}**\nBoosts: **{g.premium_subscription_count or 0}**')
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='servidor_descricao', description='Exibe descrição pública do servidor e convite configurado.')
    async def server_description(self, inter):
        g = inter.guild
        e = embed(f'🏰 {g.name}', g.description or 'Sem descrição configurada.')
        e.add_field(name='ID', value=str(g.id), inline=True)
        e.add_field(name='Criado', value=f'<t:{int(g.created_at.timestamp())}:F>', inline=True)
        e.add_field(name='Proprietário', value=f'<@{g.owner_id}>', inline=True)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='canal_info', description='Informações detalhadas de canal.')
    async def channel_info(self, inter, canal: discord.abc.GuildChannel):
        e = embed(f'🗂️ NEXUS • CANAL {canal.name}', f"ID: `{canal.id}`\nTipo: {type(canal).__name__}\nCategoria: {(canal.category.mention if canal.category else 'sem categoria')}\nCriado: <t:{int(canal.created_at.timestamp())}:F>")
        if isinstance(canal, discord.TextChannel):
            e.add_field(name='Tópico', value=clip(canal.topic or 'Sem tópico', 600), inline=False)
            e.add_field(name='Slowmode', value=f'{canal.slowmode_delay}s', inline=True)
        if isinstance(canal, discord.VoiceChannel):
            e.add_field(name='Limite', value=str(canal.user_limit or 'sem limite'), inline=True)
            e.add_field(name='Bitrate', value=f'{canal.bitrate // 1000} kbps', inline=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='servidor_config_info', description='Exibe configurações públicas do servidor.')
    async def guild_config_info(self, inter):
        g = inter.guild
        e = embed('⚙️ NEXUS • SERVER CONFIG', f"Verificação: **{g.verification_level}**\nFiltro conteúdo: **{g.explicit_content_filter}**\nNotificações: **{g.default_notifications}**\nIdioma: **{g.preferred_locale}**\nAFK timeout: **{g.afk_timeout}**s\nAFK canal: {(g.afk_channel.mention if g.afk_channel else 'não configurado')}\nVanity: **{g.vanity_url_code or 'não disponível'}**")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='nexus_guild_tools_status', description='Diagnóstico das ferramentas de servidor.')
    @app_commands.checks.has_permissions(administrator=True)
    async def guild_tools_status(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        e = embed('🧰 NEXUS • GUILD TOOLS', f"AutoMod bypass cargos: {len(cfg.get('automod_bypass_role_ids') or [])}\nCanais: {len(inter.guild.channels)}\nCargos: {len(inter.guild.roles)}\nMembros no cache: {len(inter.guild.members)}")
        await inter.response.send_message(embed=e, ephemeral=True)

async def _load_guild_tools(bot, pool):
    if bot.get_cog('NexusGuildTools') is None:
        await bot.add_cog(NexusGuildTools(bot, pool))

class NexusUtilities(commands.Cog):
    group_1 = app_commands.Group(name='util', description='NexusUtilities commands (util)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    @group_1.command(name='coinflip', description='Joga uma moeda virtual.')
    async def coinflip(self, inter):
        result = __import__('random').SystemRandom().choice(['🪙 Cara', '🪙 Coroa'])
        await reply(inter, f'🎲 Resultado: **{result}**')

    @group_1.command(name='dado', description='Rola dado com número de lados configurável.')
    async def dice(self, inter, lados: app_commands.Range[int, 2, 1000]=6, quantidade: app_commands.Range[int, 1, 10]=1):
        import random
        values = [random.SystemRandom().randint(1, lados) for _ in range(quantidade)]
        await reply(inter, f'🎲 {quantidade}d{lados}: **{values}** • total **{sum(values)}**')

    @group_1.command(name='random_numero', description='Gera número aleatório entre mínimo e máximo.')
    async def random_number(self, inter, minimo: int, maximo: int):
        if minimo > maximo:
            return await reply(inter, 'Mínimo deve ser menor ou igual ao máximo.')
        if maximo - minimo > 10 ** 12:
            return await reply(inter, 'Intervalo muito amplo.')
        import random
        value = random.SystemRandom().randint(minimo, maximo)
        await reply(inter, f'🎲 Número aleatório: **{value}**')

    @group_1.command(name='random_escolher', description='Escolhe aleatoriamente entre opções separadas por vírgula.')
    async def random_choose(self, inter, opcoes: str):
        choices = [x.strip() for x in opcoes.split(',') if x.strip()]
        if len(choices) < 2:
            return await reply(inter, 'Informe duas ou mais opções separadas por vírgula.')
        if len(choices) > 50:
            return await reply(inter, 'Máximo de 50 opções.')
        import random
        await reply(inter, f'🎯 Escolha: **{clip(random.SystemRandom().choice(choices), 300)}**')

    @group_1.command(name='random_embaralhar', description='Embaralha lista de opções.')
    async def random_shuffle(self, inter, opcoes: str):
        choices = [x.strip() for x in opcoes.split(',') if x.strip()]
        if not choices:
            return await reply(inter, 'Lista vazia.')
        if len(choices) > 50:
            return await reply(inter, 'Máximo de 50 opções.')
        import random
        random.SystemRandom().shuffle(choices)
        await reply(inter, clip('🔀 ' + ', '.join(choices), 1800))

    @group_1.command(name='texto_contar', description='Conta caracteres, palavras e linhas.')
    async def text_count(self, inter, texto: str):
        words = re.findall('\\S+', texto)
        lines = texto.splitlines() or ['']
        e = embed('📝 NEXUS • CONTAGEM DE TEXTO', f"Caracteres: **{len(texto)}**\nPalavras: **{len(words)}**\nLinhas: **{len(lines)}**\nCaracteres sem espaço: **{len(re.sub('\\\\s', '', texto))}**")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='texto_maiusculo', description='Converte texto para maiúsculas.')
    async def text_upper(self, inter, texto: str):
        await reply(inter, clip(texto.upper(), 1900))

    @group_1.command(name='texto_minusculo', description='Converte texto para minúsculas.')
    async def text_lower(self, inter, texto: str):
        await reply(inter, clip(texto.lower(), 1900))

    @group_1.command(name='texto_titulo', description='Converte texto para formato título.')
    async def text_title(self, inter, texto: str):
        await reply(inter, clip(texto.title(), 1900))

    @group_1.command(name='texto_inverter', description='Inverte caracteres do texto.')
    async def text_reverse(self, inter, texto: str):
        await reply(inter, clip(texto[::-1], 1900))

    @group_1.command(name='texto_emoji', description='Formata texto em caixa temática Nexus.')
    async def text_box(self, inter, texto: str):
        await reply(inter, clip(f'╔══════ NEXUS ══════╗\n{texto}\n╚════════════════════╝', 1900))

    @group_1.command(name='math', description='Calcula expressão aritmética simples de forma segura.')
    async def math_calc(self, inter, expressao: str):
        try:
            tree = ast.parse(expressao, mode='eval')
            allowed = (ast.Expression, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Load)
            if any((not isinstance(node, allowed) for node in ast.walk(tree))):
                return await reply(inter, 'Expressão contém operadores/tipos não permitidos.')
            if any((isinstance(n, ast.Constant) and (not isinstance(n.value, (int, float)) or abs(n.value) > 1000000000000.0) for n in ast.walk(tree))):
                return await reply(inter, 'Valores numéricos inválidos ou muito grandes.')
            result = eval(compile(tree, '<nexus-math>', 'eval'), {'__builtins__': {}}, {})
            if isinstance(result, (int, float)) and abs(result) > 1e+100:
                return await reply(inter, 'Resultado excede limite permitido.')
            await reply(inter, f'🧮 **{clip(expressao, 200)}** = **{result}**')
        except (ValueError, TypeError, ZeroDivisionError, OverflowError, SyntaxError):
            await reply(inter, 'Não consegui calcular expressão. Use operações aritméticas básicas.')

    @group_1.command(name='tempo_agora', description='Exibe horário UTC atual.')
    async def current_time(self, inter):
        now = datetime.now(timezone.utc)
        await reply(inter, f'🕒 UTC: <t:{int(now.timestamp())}:F> • <t:{int(now.timestamp())}:R>')

    @group_1.command(name='tempo_converter', description='Converte minutos, horas ou dias em segundos.')
    async def time_convert(self, inter, valor: app_commands.Range[float, 0, 1000000], unidade: str):
        unit = unidade.lower()
        factors = {'segundo': 1, 'segundos': 1, 'minuto': 60, 'minutos': 60, 'hora': 3600, 'horas': 3600, 'dia': 86400, 'dias': 86400}
        if unit not in factors:
            return await reply(inter, 'Unidade: segundos, minutos, horas ou dias.')
        seconds = valor * factors[unit]
        await reply(inter, f'⏱️ **{valor:g} {unit}** = **{seconds:g} segundos**')

    @group_1.command(name='texto_palavra', description='Busca quantidade de ocorrências de palavra no texto informado.')
    async def text_word_count(self, inter, texto: str, palavra: str):
        count = len(re.findall(re.escape(palavra), texto, re.I))
        await reply(inter, f'🔎 A palavra `{clip(palavra, 100)}` aparece **{count}** vezes no texto.')

    @group_1.command(name='texto_substituir', description='Substitui trecho em texto.')
    async def text_replace(self, inter, texto: str, alvo: str, substituto: str):
        if not alvo:
            return await reply(inter, 'Trecho de busca não pode ficar vazio.')
        result = texto.replace(alvo, substituto)
        await reply(inter, clip(result, 1900))

    @group_1.command(name='texto_limpar', description='Remove espaços duplicados e quebras excedentes.')
    async def text_clean(self, inter, texto: str):
        clean = re.sub('[ \\t]+', ' ', texto)
        clean = re.sub('\\n{3,}', '\n\n', clean).strip()
        await reply(inter, clip(clean, 1900))

    @group_1.command(name='texto_slug', description='Converte texto em slug simples.')
    async def text_slug(self, inter, texto: str):
        value = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower()
        value = re.sub('[^a-z0-9]+', '-', value).strip('-')
        await reply(inter, clip(value, 1900))

    @group_1.command(name='texto_hex', description='Converte texto para hexadecimal UTF-8.')
    async def text_hex(self, inter, texto: str):
        value = texto.encode('utf-8').hex()
        await reply(inter, clip(value, 1900))

    @group_1.command(name='texto_de_hex', description='Converte hexadecimal UTF-8 para texto.')
    async def hex_text(self, inter, hexadecimal: str):
        try:
            value = bytes.fromhex(hexadecimal).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            return await reply(inter, 'Hexadecimal inválido ou não UTF-8.')
        await reply(inter, clip(value, 1900))

    @group_1.command(name='texto_base64', description='Codifica texto em Base64.')
    async def text_base64(self, inter, texto: str):
        import base64
        await reply(inter, clip(base64.b64encode(texto.encode()).decode(), 1900))

    @group_1.command(name='texto_base64_decode', description='Decodifica Base64 para UTF-8.')
    async def base64_text(self, inter, codigo: str):
        import base64
        try:
            value = base64.b64decode(codigo, validate=True).decode('utf-8')
        except Exception:
            return await reply(inter, 'Base64 inválido ou não UTF-8.')
        await reply(inter, clip(value, 1900))

    @group_1.command(name='texto_url_encode', description='Codifica texto para URL.')
    async def url_encode(self, inter, texto: str):
        import urllib.parse
        await reply(inter, clip(urllib.parse.quote(texto, safe=''), 1900))

    @group_1.command(name='texto_url_decode', description='Decodifica URL-encoded text.')
    async def url_decode(self, inter, texto: str):
        import urllib.parse
        await reply(inter, clip(urllib.parse.unquote(texto), 1900))

    @group_1.command(name='nexus_utilities_status', description='Lista utilitários do Nexus.')
    async def utility_status(self, inter):
        await reply(inter, '🧰 Utilitários: coinflip, dado, random_numero, random_escolher, random_embaralhar, math, tempo_agora, tempo_converter, texto_contar, texto_maiusculo/minusculo/titulo/inverter/limpar/substituir/slug/hex/Base64/URL. Ferramentas usam cálculos locais; não enviam dados externos.')

async def _load_utilities(bot, pool):
    if bot.get_cog('NexusUtilities') is None:
        await bot.add_cog(NexusUtilities(bot, pool))

class NexusStaffMetrics(commands.Cog):
    group_1 = app_commands.Group(name='staff_metrics', description='NexusStaffMetrics commands (staff_metrics)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_check(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff-only command.')
        return False

    @commands.Cog.listener()
    async def on_message(self, msg):
        if not msg.guild or msg.author.bot:
            return
        cfg = await self.bot.get_cog('Systems').config(msg.guild.id)
        if not staff(msg.author, cfg):
            return
        today = datetime.now(timezone.utc).date()
        await self.pool.execute('INSERT INTO nexus_staff_activity(guild_id,user_id,activity_date,messages) VALUES($1,$2,$3,1) ON CONFLICT(guild_id,user_id,activity_date) DO UPDATE SET messages=nexus_staff_activity.messages+1', msg.guild.id, msg.author.id, today)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if not ctx.guild or ctx.author.bot:
            return
        cfg = await self.bot.get_cog('Systems').config(ctx.guild.id)
        if not staff(ctx.author, cfg):
            return
        today = datetime.now(timezone.utc).date()
        await self.pool.execute('INSERT INTO nexus_staff_activity(guild_id,user_id,activity_date,commands) VALUES($1,$2,$3,1) ON CONFLICT(guild_id,user_id,activity_date) DO UPDATE SET commands=nexus_staff_activity.commands+1', ctx.guild.id, ctx.author.id, today)

    @group_1.command(name='staff_atividade', description='Resumo de atividade staff em período (admin/staff).')
    async def staff_activity(self, inter, dias: app_commands.Range[int, 1, 90]=7):
        if not await self.staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT user_id,SUM(messages) AS messages,SUM(commands) AS commands,COUNT(*) AS days FROM nexus_staff_activity WHERE guild_id=$1 AND activity_date>=CURRENT_DATE-($2::int) GROUP BY user_id ORDER BY SUM(messages)+SUM(commands) DESC LIMIT 30', inter.guild.id, dias)
        e = embed(f'🛡️ NEXUS • ATIVIDADE STAFF ({dias}d)', f'{len(rows)} membros com atividade registrada')
        for r in rows:
            e.add_field(name=f"<@{r['user_id']}>", value=f"Mensagens: **{r['messages'] or 0}** • comandos: **{r['commands'] or 0}** • dias ativos: **{r['days']}**", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='staff_atividade_membro', description='Consulta atividade de membro staff.')
    async def staff_activity_member(self, inter, membro: discord.User, dias: app_commands.Range[int, 1, 90]=7):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT SUM(messages) AS messages,SUM(commands) AS commands,COUNT(*) AS days FROM nexus_staff_activity WHERE guild_id=$1 AND user_id=$2 AND activity_date>=CURRENT_DATE-($3::int)', inter.guild.id, membro.id, dias)
        await reply(inter, f"📊 {membro.mention} • últimos **{dias} dias**\nMensagens staff: **{row['messages'] or 0}**\nComandos staff: **{row['commands'] or 0}**\nDias ativos: **{row['days'] or 0}**")

    @group_1.command(name='staff_meta_criar', description='Cria meta semanal de atividade staff.')
    async def staff_goal_create(self, inter, membro: discord.Member, mensagens: int, comandos: int, semana_inicio: str=''):
        if not await self.staff_check(inter):
            return
        try:
            dateval = datetime.strptime(semana_inicio, '%Y-%m-%d').date() if semana_inicio else datetime.now(timezone.utc).date()
        except ValueError:
            return await reply(inter, 'Data inválida. Use YYYY-MM-DD ou deixe vazio para hoje.')
        gid = await self.pool.fetchval('INSERT INTO nexus_staff_goals(guild_id,user_id,week_start,message_goal,command_goal,created_by) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', inter.guild.id, membro.id, dateval, mensagens, comandos, inter.user.id)
        await reply(inter, f'🎯 Meta **#{gid}** criada para {membro.mention}.')

    @group_1.command(name='staff_meta_lista', description='Lista metas staff cadastradas.')
    async def staff_goal_list(self, inter):
        if not await self.staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT id,user_id,week_start,message_goal,command_goal FROM nexus_staff_goals WHERE guild_id=$1 ORDER BY week_start DESC LIMIT 25', inter.guild.id)
        e = embed('🎯 NEXUS • METAS STAFF', f'{len(rows)} metas')
        for r in rows:
            e.add_field(name=f"#{r['id']} • <@{r['user_id']}> • {r['week_start']}", value=f"Mensagens: {r['message_goal']} • comandos: {r['command_goal']}", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='staff_meta_progresso', description='Mostra progresso de meta staff por ID.')
    async def staff_goal_progress(self, inter, meta_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM nexus_staff_goals WHERE guild_id=$1 AND id=$2', inter.guild.id, meta_id)
        if not row:
            return await reply(inter, 'Meta não encontrada.')
        activity = await self.pool.fetchrow('SELECT SUM(messages) AS messages,SUM(commands) AS commands FROM nexus_staff_activity WHERE guild_id=$1 AND user_id=$2 AND activity_date>=$3 AND activity_date<$3+7', inter.guild.id, row['user_id'], row['week_start'])
        msg = activity['messages'] or 0
        cmd = activity['commands'] or 0
        e = embed(f'🎯 META STAFF • #{meta_id}', f"Usuário: <@{row['user_id']}>\nPeríodo: {row['week_start']}\nMensagens: **{msg}/{row['message_goal']}**\nComandos: **{cmd}/{row['command_goal']}**\nProgresso mensagens: **{min(100, msg / max(row['message_goal'], 1) * 100):.1f}%**\nProgresso comandos: **{min(100, cmd / max(row['command_goal'], 1) * 100):.1f}%**")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='staff_meta_remover', description='Remove meta staff por ID.')
    async def staff_goal_remove(self, inter, meta_id: int):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute('DELETE FROM nexus_staff_goals WHERE guild_id=$1 AND id=$2', inter.guild.id, meta_id)
        await reply(inter, 'Meta removida.' if res.endswith('1') else 'Meta não encontrada.')

    @group_1.command(name='staff_atividade_reset', description='Apaga atividade de membro em período (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_activity_reset(self, inter, membro: discord.User, dias: app_commands.Range[int, 1, 90]=30):
        res = await self.pool.execute('DELETE FROM nexus_staff_activity WHERE guild_id=$1 AND user_id=$2 AND activity_date>=CURRENT_DATE-($3::int)', inter.guild.id, membro.id, dias)
        await reply(inter, f'📊 Atividade resetada. Registros removidos: {res.split()[-1]}.')

    @group_1.command(name='staff_atividade_status', description='Diagnóstico do ledger de atividade staff.')
    @app_commands.checks.has_permissions(administrator=True)
    async def staff_activity_status(self, inter):
        count = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_staff_activity WHERE guild_id=$1', inter.guild.id)
        goals = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_staff_goals WHERE guild_id=$1', inter.guild.id)
        await inter.response.send_message(embed=embed('📊 NEXUS • STAFF METRICS', f'Activity records: **{count}**\nGoals: **{goals}**\nTracking records only messages and commands while configured staff is recognized.'), ephemeral=True)

async def _load_staff_metrics(bot, pool):
    if bot.get_cog('NexusStaffMetrics') is None:
        await bot.add_cog(NexusStaffMetrics(bot, pool))

class NexusRecurringAnnouncements(commands.Cog):
    group_1 = app_commands.Group(name='recurring', description='NexusRecurringAnnouncements commands (recurring)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)
        self.schedule_loop.start()

    def cog_unload(self):
        self.schedule_loop.cancel()

    async def staff_check(self, inter):
        if inter.user.guild_permissions.manage_messages:
            return True
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Permissão de staff necessária.')
        return False

    @tasks.loop(minutes=1)
    async def schedule_loop(self):
        await self.bot.wait_until_ready()
        rows = await self.pool.fetch('SELECT id,guild_id,channel_id,title,content,next_run,interval_minutes FROM nexus_recurring_announcements WHERE active=TRUE AND next_run<=NOW() ORDER BY next_run LIMIT 30')
        for row in rows:
            guild = self.bot.get_guild(row['guild_id'])
            channel = guild.get_channel(row['channel_id']) if guild else None
            if not channel:
                await self.pool.execute('UPDATE nexus_recurring_announcements SET active=FALSE WHERE id=$1', row['id'])
                continue
            e = embed(f"📢 {clip(row['title'], 220)}", clip(row['content'], 4000))
            cfg = await self.bot.get_cog('Systems').config(row['guild_id'])
            if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']):
                e.set_image(url=cfg['theme_image_url'])
            try:
                await channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                continue
            await self.pool.execute("UPDATE nexus_recurring_announcements SET next_run=NOW()+($2::int*INTERVAL '1 minute'),last_sent=NOW() WHERE id=$1", row['id'], row['interval_minutes'])

    @schedule_loop.before_loop
    async def before_schedule(self):
        await self.bot.wait_until_ready()

    @group_1.command(name='anuncio_recorrente_criar', description='Cria anúncio recorrente com intervalo em minutos.')
    async def recurring_create(self, inter, canal: discord.TextChannel, titulo: str, conteudo: str, intervalo_minutos: app_commands.Range[int, 60, 100800], primeiro_envio_minutos: app_commands.Range[int, 1, 10080]=60):
        if not await self.staff_check(inter):
            return
        first = datetime.now(timezone.utc) + timedelta(minutes=primeiro_envio_minutos)
        rid = await self.pool.fetchval('INSERT INTO nexus_recurring_announcements(guild_id,creator_id,channel_id,title,content,interval_minutes,next_run,active) VALUES($1,$2,$3,$4,$5,$6,$7,TRUE) RETURNING id', inter.guild.id, inter.user.id, canal.id, clip(titulo, 220), clip(conteudo, 4000), intervalo_minutos, first)
        await reply(inter, f'🔁 Anúncio recorrente **#{rid}** criado. Primeiro envio <t:{int(first.timestamp())}:R>; intervalo **{intervalo_minutos} min**.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Anúncio recorrente criado', {'schedule': rid, 'channel': canal.id, 'interval': intervalo_minutos})

    @group_1.command(name='anuncio_recorrente_lista', description='Lista anúncios recorrentes (staff).')
    async def recurring_list(self, inter):
        if not await self.staff_check(inter):
            return
        rows = await self.pool.fetch('SELECT id,title,channel_id,interval_minutes,next_run,active FROM nexus_recurring_announcements WHERE guild_id=$1 ORDER BY id DESC LIMIT 25', inter.guild.id)
        e = embed('🔁 NEXUS • ANÚNCIOS RECORRENTES', f'{len(rows)} schedules')
        for r in rows:
            e.add_field(name=f"#{r['id']} • {r['title']} • {('ativo' if r['active'] else 'pausado')}", value=f"Canal <#{r['channel_id']}> • intervalo {r['interval_minutes']} min • próximo <t:{int(r['next_run'].timestamp())}:R>", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='anuncio_recorrente_pausar', description='Pausa/reativa schedule recorrente.')
    async def recurring_toggle(self, inter, schedule_id: int, ativar: bool):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute('UPDATE nexus_recurring_announcements SET active=$3 WHERE guild_id=$1 AND id=$2', inter.guild.id, schedule_id, ativar)
        await reply(inter, 'Schedule atualizado.' if res.endswith('1') else 'Schedule não encontrado.')

    @group_1.command(name='anuncio_recorrente_remover', description='Remove schedule recorrente.')
    async def recurring_remove(self, inter, schedule_id: int):
        if not await self.staff_check(inter):
            return
        res = await self.pool.execute('DELETE FROM nexus_recurring_announcements WHERE guild_id=$1 AND id=$2', inter.guild.id, schedule_id)
        await reply(inter, 'Schedule removido.' if res.endswith('1') else 'Schedule não encontrado.')

    @group_1.command(name='anuncio_recorrente_detalhe', description='Consulta schedule recorrente por ID.')
    async def recurring_detail(self, inter, schedule_id: int):
        if not await self.staff_check(inter):
            return
        row = await self.pool.fetchrow('SELECT * FROM nexus_recurring_announcements WHERE guild_id=$1 AND id=$2', inter.guild.id, schedule_id)
        if not row:
            return await reply(inter, 'Schedule não encontrado.')
        e = embed(f'🔁 SCHEDULE • #{schedule_id}', f"Título: **{row['title']}**\nCanal: <#{row['channel_id']}>\nIntervalo: **{row['interval_minutes']} min**\nPróximo: <t:{int(row['next_run'].timestamp())}:F>\nAtivo: **{row['active']}**\n\n{clip(row['content'], 2500)}")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='anuncio_recorrente_status', description='Diagnóstico de schedules recorrentes.')
    @app_commands.checks.has_permissions(administrator=True)
    async def recurring_status(self, inter):
        total = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_recurring_announcements WHERE guild_id=$1', inter.guild.id)
        active = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_recurring_announcements WHERE guild_id=$1 AND active=TRUE', inter.guild.id)
        await inter.response.send_message(embed=embed('🔁 NEXUS • RECURRING STATUS', f'Total: **{total}**\nAtivos: **{active}**\nScheduler: **running** (loop 60s)'), ephemeral=True)

async def _load_recurring(bot, pool):
    if bot.get_cog('NexusRecurringAnnouncements') is None:
        await bot.add_cog(NexusRecurringAnnouncements(bot, pool))

class NexusSuggestionVotes(commands.Cog):
    group_1 = app_commands.Group(name='suggestion_votes', description='NexusSuggestionVotes commands (suggestion_votes)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def cog_load(self):
        self.bot.add_view(SuggestionVoteView())

    @group_1.command(name='sugestao_votos', description='Consulta contagem de votos de sugestão.')
    async def suggestion_vote_counts(self, inter, sugestao_id: int):
        row = await self.pool.fetchrow('SELECT message_id,content,status FROM sistemas_suggestions WHERE guild_id=$1 AND id=$2', inter.guild.id, sugestao_id)
        if not row:
            return await reply(inter, 'Sugestão não encontrada.')
        up = await self.pool.fetchval('SELECT COUNT(*) FROM sistemas_suggestion_votes WHERE guild_id=$1 AND suggestion_id=$2 AND choice=$3', inter.guild.id, sugestao_id, 'up')
        down = await self.pool.fetchval('SELECT COUNT(*) FROM sistemas_suggestion_votes WHERE guild_id=$1 AND suggestion_id=$2 AND choice=$3', inter.guild.id, sugestao_id, 'down')
        e = embed(f'💡 VOTOS • SUGESTÃO #{sugestao_id}', f"{clip(row['content'], 1000)}\nStatus: **{row['status']}**\n\n👍 **{up}** • 👎 **{down}**")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='sugestao_voto_reset', description='Reseta votos de sugestão (staff).')
    async def suggestion_vote_reset(self, inter, sugestao_id: int):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if not staff(inter.user, cfg):
            return await reply(inter, '⛔ Staff necessária.')
        res = await self.pool.execute('DELETE FROM sistemas_suggestion_votes WHERE guild_id=$1 AND suggestion_id=$2', inter.guild.id, sugestao_id)
        await reply(inter, f'Votos resetados. Registros removidos: {res.split()[-1]}.')

class SuggestionVoteView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    async def vote(self, inter, choice):
        row = await inter.client.get_cog('Systems').pool.fetchrow('SELECT id FROM sistemas_suggestions WHERE guild_id=$1 AND message_id=$2', inter.guild.id, inter.message.id)
        if not row:
            return await reply(inter, 'Sugestão não encontrada no banco.')
        await inter.client.get_cog('Systems').pool.execute('INSERT INTO sistemas_suggestion_votes(guild_id,suggestion_id,user_id,choice) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,suggestion_id,user_id) DO UPDATE SET choice=EXCLUDED.choice,updated_at=NOW()', inter.guild.id, row['id'], inter.user.id, choice)
        up = await inter.client.get_cog('Systems').pool.fetchval('SELECT COUNT(*) FROM sistemas_suggestion_votes WHERE guild_id=$1 AND suggestion_id=$2 AND choice=$3', inter.guild.id, row['id'], 'up')
        down = await inter.client.get_cog('Systems').pool.fetchval('SELECT COUNT(*) FROM sistemas_suggestion_votes WHERE guild_id=$1 AND suggestion_id=$2 AND choice=$3', inter.guild.id, row['id'], 'down')
        if inter.message.embeds:
            e = inter.message.embeds[0]
            e.set_footer(text=f'NEXUS • Votos 👍 {up} | 👎 {down}')
            await inter.message.edit(embed=e, view=self)
        await reply(inter, f"Voto registrado: {('👍 apoio' if choice == 'up' else '👎 não apoio')}.")

    @discord.ui.button(label='Apoiar', style=discord.ButtonStyle.success, emoji='👍', custom_id='nexus:suggestion:up')
    async def up(self, inter, button):
        await self.vote(inter, 'up')

    @discord.ui.button(label='Não apoiar', style=discord.ButtonStyle.danger, emoji='👎', custom_id='nexus:suggestion:down')
    async def down(self, inter, button):
        await self.vote(inter, 'down')

async def _load_suggestion_votes(bot, pool):
    if bot.get_cog('NexusSuggestionVotes') is None:
        await bot.add_cog(NexusSuggestionVotes(bot, pool))

class NexusModerationAnalytics(commands.Cog):
    group_1 = app_commands.Group(name='mod_stats', description='NexusModerationAnalytics commands (mod_stats)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_auth(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff necessária.')
        return False

    @group_1.command(name='moderacao_stats', description='Resumo de punições por tipo e estado (staff).')
    async def moderation_stats(self, inter, dias: app_commands.Range[int, 1, 365]=30):
        if not await self.staff_auth(inter):
            return
        rows = await self.pool.fetch("SELECT action,COUNT(*) AS total,SUM(CASE WHEN active THEN 1 ELSE 0 END) AS active FROM sistemas_cases WHERE guild_id=$1 AND created_at>=NOW()-($2::int*INTERVAL '1 day') GROUP BY action ORDER BY total DESC", inter.guild.id, dias)
        total = sum((r['total'] for r in rows))
        active = sum((r['active'] or 0 for r in rows))
        e = embed(f'⚖️ NEXUS • MODERAÇÃO ({dias}d)', f'Total: **{total}**\nAtivas: **{active}**\nRevogadas/inativas: **{total - active}**')
        for r in rows:
            e.add_field(name=r['action'], value=f"{r['total']} registros • {r['active'] or 0} ativos", inline=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='moderacao_top', description='Ranking de moderadores por casos registrados.')
    async def moderation_top(self, inter, dias: app_commands.Range[int, 1, 365]=30):
        if not await self.staff_auth(inter):
            return
        rows = await self.pool.fetch("SELECT moderator_id,COUNT(*) AS cases FROM sistemas_cases WHERE guild_id=$1 AND created_at>=NOW()-($2::int*INTERVAL '1 day') GROUP BY moderator_id ORDER BY cases DESC LIMIT 15", inter.guild.id, dias)
        e = embed(f'⚖️ NEXUS • MODERADORES ({dias}d)', f'{len(rows)} moderadores')
        for idx, r in enumerate(rows, 1):
            e.add_field(name=f"{idx}. <@{r['moderator_id']}>", value=f"{r['cases']} registros", inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='moderacao_config_aplicar', description='Define punições aprovadas que podem executar automaticamente.')
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_auto_apply(self, inter, tipos_csv: str):
        allowed = {'warn', 'timeout', 'mute', 'kick', 'ban', 'hackban', 'quarentena'}
        types = [x.strip().lower() for x in tipos_csv.split(',') if x.strip()]
        if any((x not in allowed for x in types)):
            return await reply(inter, f'Tipos permitidos: {sorted(allowed)}')
        await self.bot.get_cog('Systems').setcfg(inter.guild.id, 'request_auto_types', list(dict.fromkeys(types)))
        await reply(inter, f"⚖️ Execução automática configurada para: {types or 'nenhuma'}.")

    @group_1.command(name='moderacao_config_aplicar_status', description='Consulta ações automáticas configuradas.')
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_auto_apply_status(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        await reply(inter, f"⚖️ Solicitações aprovadas executam automaticamente: **{cfg.get('request_auto_types') or 'nenhuma'}**. A execução depende de permissão e hierarquia.")

    @group_1.command(name='moderacao_reverter', description='Reverte punição por caso (staff) quando possível.')
    async def moderation_revert(self, inter, caso_id: int, motivo: str):
        if not await self.staff_auth(inter):
            return
        row = await self.pool.fetchrow('SELECT user_id,action,active FROM sistemas_cases WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        if not row:
            return await reply(inter, 'Caso não encontrado.')
        uid = row['user_id']
        action = row['action']
        guild = inter.guild
        try:
            if action in ('ban', 'hackban', 'tempban'):
                await guild.unban(discord.Object(id=uid), reason=f'Revert case #{caso_id} by {inter.user.id}: {motivo}')
            elif action in ('timeout', 'mute'):
                member = guild.get_member(uid)
                if not member:
                    return await reply(inter, 'Membro não está no servidor; não é possível remover timeout.')
                await member.timeout(None, reason=f'Revert case #{caso_id}: {motivo}')
            elif action == 'quarentena':
                await self.bot.get_cog('Systems').quarantine_release(guild, uid, inter.user.id, motivo)
            else:
                return await reply(inter, 'Tipo de punição não possui reversão automática. Revogue o caso manualmente se necessário.')
        except discord.NotFound:
            return await reply(inter, 'Punição não está ativa no Discord.')
        except discord.HTTPException:
            return await reply(inter, 'Discord recusou reversão; confira permissões.')
        await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE guild_id=$1 AND id=$2', guild.id, caso_id)
        await reply(inter, f'♻️ Caso **#{caso_id}** revertido e marcado inativo.')
        await self.bot.get_cog('Systems').audit(guild, inter.user.id, 'Punição revertida', {'case_id': caso_id, 'target': uid, 'action': action, 'reason': motivo}, 'log_punishment_channel_id', GREEN)

    @group_1.command(name='moderacao_case_limpar', description='Remove registros de caso de usuário (admin).')
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_case_delete(self, inter, caso_id: int, confirmar: bool=False):
        if not confirmar:
            return await reply(inter, 'Para confirmar, execute novamente com `confirmar=true`. Esta operação apaga histórico de moderação.')
        row = await self.pool.fetchrow('SELECT user_id,action FROM sistemas_cases WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        if not row:
            return await reply(inter, 'Caso não encontrado.')
        await self.pool.execute('DELETE FROM sistemas_cases WHERE guild_id=$1 AND id=$2', inter.guild.id, caso_id)
        await reply(inter, f'Caso **#{caso_id}** removido do banco.')
        await self.bot.get_cog('Systems').audit(inter.guild, inter.user.id, 'Caso apagado', {'case_id': caso_id, 'user': row['user_id'], 'action': row['action']})

    @group_1.command(name='moderacao_user_summary', description='Resumo de histórico de usuário para staff.')
    async def moderation_user_summary(self, inter, membro: discord.User):
        if not await self.staff_auth(inter):
            return
        counts = await self.pool.fetchrow('SELECT COUNT(*) AS total,SUM(CASE WHEN active THEN 1 ELSE 0 END) AS active FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        reports = await self.pool.fetchval('SELECT COUNT(*) FROM sistemas_reports WHERE guild_id=$1 AND target_id=$2', inter.guild.id, membro.id)
        requests = await self.pool.fetchval('SELECT COUNT(*) FROM sistemas_requests WHERE guild_id=$1 AND target_id=$2', inter.guild.id, membro.id)
        quarantine = await self.pool.fetchval('SELECT active FROM nexus_quarantine WHERE guild_id=$1 AND user_id=$2', inter.guild.id, membro.id)
        e = embed(f'⚖️ NEXUS • RESUMO {membro}', f"Casos: **{counts['total']}**\nCasos ativos: **{counts['active'] or 0}**\nDenúncias: **{reports}**\nSolicitações: **{requests}**\nQuarentena ativa: **{bool(quarantine)}**")
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='moderacao_pendentes', description='Resumo de denúncias, pedidos e apelações pendentes.')
    async def moderation_pending(self, inter):
        if not await self.staff_auth(inter):
            return
        counts = []
        for label, table in [('Denúncias', 'sistemas_reports'), ('Solicitações', 'sistemas_requests'), ('Apelações', 'sistemas_appeals'), ('Candidaturas', 'nexus_applications')]:
            try:
                n = await self.pool.fetchval(f"SELECT COUNT(*) FROM {table} WHERE guild_id=$1 AND status='pending'", inter.guild.id)
                counts.append(f'• {label}: **{n}**')
            except Exception as ex:
                counts.append(f'• {label}: não disponível ({type(ex).__name__})')
        await inter.response.send_message(embed=embed('📥 NEXUS • PENDÊNCIAS', '\n'.join(counts)), ephemeral=True)

    @group_1.command(name='moderacao_status', description='Diagnóstico de sistema de punições.')
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_status(self, inter):
        cases = await self.pool.fetchval('SELECT COUNT(*) FROM sistemas_cases WHERE guild_id=$1', inter.guild.id)
        requests = await self.pool.fetchval("SELECT COUNT(*) FROM sistemas_requests WHERE guild_id=$1 AND status='pending'", inter.guild.id)
        appeals = await self.pool.fetchval("SELECT COUNT(*) FROM sistemas_appeals WHERE guild_id=$1 AND status='pending'", inter.guild.id)
        await inter.response.send_message(embed=embed('⚖️ NEXUS • MODERATION STATUS', f'Casos: **{cases}**\nSolicitações pendentes: **{requests}**\nApelações pendentes: **{appeals}**'), ephemeral=True)

async def _load_moderation_analytics(bot, pool):
    if bot.get_cog('NexusModerationAnalytics') is None:
        await bot.add_cog(NexusModerationAnalytics(bot, pool))

class NexusModerationTemplates(commands.Cog):
    group_1 = app_commands.Group(name='templates', description='NexusModerationTemplates commands (templates)')

    def __init__(self, bot, pool):
        self.bot, self.pool = (bot, pool)

    async def staff_gate(self, inter):
        cfg = await self.bot.get_cog('Systems').config(inter.guild.id)
        if staff(inter.user, cfg):
            return True
        await reply(inter, '⛔ Staff necessária.')
        return False

    @group_1.command(name='motivo_template_criar', description='Cria template de motivo para moderação (staff).')
    async def template_create(self, inter, nome: str, texto: str):
        if not await self.staff_gate(inter):
            return
        name = nome.lower().strip().replace(' ', '_')
        if not re.fullmatch('[a-z0-9_-]{1,32}', name):
            return await reply(inter, 'Nome inválido.')
        await self.pool.execute('INSERT INTO nexus_moderation_templates(guild_id,name,text,created_by) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,name) DO UPDATE SET text=EXCLUDED.text,created_by=EXCLUDED.created_by,updated_at=NOW()', inter.guild.id, name, clip(texto, 1000), inter.user.id)
        await reply(inter, f'📝 Template `{name}` salvo.')

    @group_1.command(name='motivo_template_lista', description='Lista templates de motivos staff.')
    async def template_list(self, inter):
        if not await self.staff_gate(inter):
            return
        rows = await self.pool.fetch('SELECT name,text FROM nexus_moderation_templates WHERE guild_id=$1 ORDER BY name', inter.guild.id)
        e = embed('📝 NEXUS • TEMPLATES DE MODERAÇÃO', f'{len(rows)} templates')
        for r in rows:
            e.add_field(name=r['name'], value=clip(r['text'], 400), inline=False)
        await inter.response.send_message(embed=e, ephemeral=True)

    @group_1.command(name='motivo_template_remover', description='Remove template de motivo.')
    async def template_remove(self, inter, nome: str):
        if not await self.staff_gate(inter):
            return
        res = await self.pool.execute('DELETE FROM nexus_moderation_templates WHERE guild_id=$1 AND name=$2', inter.guild.id, nome.lower().strip())
        await reply(inter, 'Template removido.' if res.endswith('1') else 'Template não encontrado.')

    @group_1.command(name='punir_template', description='Aplica punição usando template de motivo salvo.')
    async def punish_template(self, inter, tipo: str, usuario_id: str, template: str, minutos: Optional[app_commands.Range[int, 1, 40320]]=None, detalhe: str=''):
        if not await self.staff_gate(inter):
            return
        if not usuario_id.isdigit():
            return await reply(inter, 'ID inválido.')
        row = await self.pool.fetchrow('SELECT text FROM nexus_moderation_templates WHERE guild_id=$1 AND name=$2', inter.guild.id, template.lower().strip())
        if not row:
            return await reply(inter, 'Template não encontrado.')
        reason = clip(row['text'].replace('{detalhe}', clip(detalhe, 500)).replace('{staff}', inter.user.display_name).replace('{server}', inter.guild.name), 1200)
        try:
            caseid = await self.bot.get_cog('Systems').punish(inter.guild, int(usuario_id), inter.user, tipo.lower(), reason, minutos)
        except Exception as exc:
            return await reply(inter, clip(f'Não foi possível aplicar: {exc}', 900))
        await reply(inter, f'⚖️ Punição aplicada pelo template. Caso **#{caseid}**.')

    @group_1.command(name='moderacao_template_info', description='Ajuda sobre templates de motivo.')
    async def template_info(self, inter):
        await reply(inter, '📝 Templates de motivo reutilizam texto para punições. Variáveis: `{detalhe}`, `{staff}`, `{server}`. Use `/motivo_template_criar`, `/motivo_template_lista` e `/punir_template`.')

    @group_1.command(name='nexus_templates_status', description='Diagnóstico de templates de moderação.')
    @app_commands.checks.has_permissions(administrator=True)
    async def template_status(self, inter):
        n = await self.pool.fetchval('SELECT COUNT(*) FROM nexus_moderation_templates WHERE guild_id=$1', inter.guild.id)
        await inter.response.send_message(embed=embed('📝 NEXUS • MODERATION TEMPLATES', f'{n} templates cadastrados.'), ephemeral=True)

async def _load_moderation_templates(bot, pool):
    if bot.get_cog('NexusModerationTemplates') is None:
        await bot.add_cog(NexusModerationTemplates(bot, pool))
