# -*- coding: utf-8 -*-
"""Nexus systems extension. Python 3.13 / discord.py 2.x / asyncpg.
Loads from the untouched main.py, reuses its __main__.db_pool and keeps legacy prefix !.
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
PURPLE=discord.Colour(0x7C3AED); BLUE=discord.Colour(0x2563EB); RED=discord.Colour(0xDC2626); GREEN=discord.Colour(0x16A34A); GOLD=discord.Colour(0xD97706); BLACK=discord.Colour(0x111018)
VISUALS={"shield":"https://files.catbox.moe/gsbbt1.png","banner":"https://files.catbox.moe/9nlwvg.png","reference":"https://files.catbox.moe/8w3qcf.jpg"}
EMOJI={"alert":"<:emoji_33:1575019806636245012>","github":"<:emoji_34:1575019961322053832>","crown":"<:emoji_13:1556437078248656986>","tools":"<:emoji_19:1556439034891599952>","shield":"<:emoji_3:1556432452115898458>","search":"<:emoji_30:157501938723534858>","voice":"<:emoji_32:1575019682598092810>","members":"<:emoji_17:1556438860798501016>","ban":"<:emoji_10:1556436879086452766>","web":"<:emoji_12:1556437008778534942>","timer":"<:emoji_18:1556438970500522024>","calendar":"<:emoji_20:1556439152625713264>","id":"<:emoji_22:1556439311984103424>","bell":"<:emoji_6:1556436410037305386>","pin":"<:emoji_17:1556438912308617256>"}
DEFAULTS={"trusted_admin_ids":[],"staff_role_ids":[],"reviewer_role_id":None,"quarantine_role_id":None,"quarantine_channel_id":None,"request_channel_id":None,"appeal_channel_id":None,"approved_channel_id":None,"denied_channel_id":None,"report_channel_id":None,"suggestion_channel_id":None,"welcome_channel_id":None,"recruitment_channel_id":None,"welcome_message":"Bem-vindo(a), {member}, ao {server}!","autorole_id":None,"temp_voice_trigger_id":None,"temp_voice_category_id":None,"log_server_channel_id":None,"log_member_channel_id":None,"log_role_channel_id":None,"log_punishment_channel_id":None,"log_internal_channel_id":None,"anti_raid_enabled":False,"anti_raid_threshold":6,"anti_raid_window_seconds":12,"anti_nuke_enabled":False,"anti_nuke_threshold":4,"anti_spam_enabled":False,"anti_links_enabled":False,"anti_invites_enabled":False,"filter_words":[],"max_mentions":5,"spam_count":5,"spam_window":8,"request_auto_types":[],"xp_enabled":False,"xp_cooldown":60,"theme_image_url":VISUALS["banner"],"backup_interval_hours":24,"economy_daily":100,"economy_work_min":25,"economy_work_max":100,"economy_cooldown":3600,"remote_admin_ids":[],"remote_enabled":False,"remote_log_channel_id":None,"shop_currency":"BRL","payment_provider":"disabled","payment_webhook_secret":None,"payment_api_key":None}

def embed(title,description='',color=PURPLE):
 e=discord.Embed(title=title,description=description,color=color,timestamp=datetime.now(timezone.utc)); e.set_footer(text='NEXUS • Administração & Comunidade'); return e

def clip(v,n=1000):
 s=str(v); return s if len(s)<=n else s[:n-1]+'…'
def url_ok(u): return not u or bool(re.match(r'^https?://',str(u),re.I))
async def reply(inter,content=None,em=None):
 if inter.response.is_done(): await inter.followup.send(content=content,embed=em,ephemeral=True)
 else: await inter.response.send_message(content=content,embed=em,ephemeral=True)
def staff(member,cfg):
 if not isinstance(member,discord.Member): return False
 return member.guild_permissions.administrator or member.guild_permissions.manage_guild or any(r.id in set(cfg.get('staff_role_ids') or [])|({cfg['reviewer_role_id']} if cfg.get('reviewer_role_id') else set()) for r in member.roles)
def hierarchy(actor,target,botmember):
 if actor.id==target.id:return False,'Você não pode agir contra si mesmo.'
 if target.id==actor.guild.owner_id:return False,'O proprietário não pode ser alvo dessa ação.'
 if actor.id!=actor.guild.owner_id and target.top_role>=actor.top_role:return False,'O alvo possui cargo igual ou superior ao seu.'
 if target.top_role>=botmember.top_role:return False,'O cargo do alvo está acima ou igual ao cargo do bot.'
 return True,''

class Systems(commands.Cog):
 def __init__(self,bot,pool):
  self.bot,self.pool=bot,pool; self.started=time.monotonic(); self.join_windows=defaultdict(deque); self.msg_windows=defaultdict(deque); self.voice_locks=defaultdict(asyncio.Lock); self.quarantine_task=self.expiry_loop; self.expiry_loop.start(); self.backup_loop.start()
 async def cog_load(self):
  await self.schema(); self.bot.add_view(NexusPublicPanel()); self.bot.add_view(NexusRemotePanel())
  for row in await self.pool.fetch("SELECT id,review_message_id FROM sistemas_requests WHERE status='pending' AND review_message_id IS NOT NULL"):
   self.bot.add_view(RequestDecisionView(int(row['id'])),message_id=row['review_message_id'])
  for row in await self.pool.fetch("SELECT id,review_message_id FROM sistemas_appeals WHERE status='pending' AND review_message_id IS NOT NULL"):
   self.bot.add_view(AppealDecisionView(int(row['id'])),message_id=row['review_message_id'])
 def cog_unload(self): self.expiry_loop.cancel(); self.backup_loop.cancel()
 async def schema(self):
  ddl=[
  "CREATE TABLE IF NOT EXISTS sistemas_config(guild_id BIGINT PRIMARY KEY,data JSONB NOT NULL DEFAULT '{}'::jsonb,updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS sistemas_cases(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),active BOOLEAN NOT NULL DEFAULT TRUE)",
  "CREATE TABLE IF NOT EXISTS sistemas_requests(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,requester_id BIGINT NOT NULL,target_id BIGINT NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,occurred TEXT,witnesses TEXT,evidence_url TEXT,evidence_attachment_url TEXT,duration_minutes INTEGER,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,decision_reason TEXT,review_message_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)",
  "CREATE TABLE IF NOT EXISTS sistemas_appeals(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,case_id BIGINT NOT NULL,appellant_id BIGINT NOT NULL,explanation TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,review_message_id BIGINT,decision_reason TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),decided_at TIMESTAMPTZ)",
  "CREATE TABLE IF NOT EXISTS sistemas_afk(guild_id BIGINT NOT NULL,user_id BIGINT,reason TEXT,since TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS sistemas_staff(guild_id BIGINT NOT NULL,user_id BIGINT,active BOOLEAN NOT NULL DEFAULT TRUE,last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),role_name TEXT,PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS sistemas_temp_voice(channel_id BIGINT PRIMARY KEY,guild_id BIGINT NOT NULL,owner_id BIGINT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS sistemas_backups(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS sistemas_audit(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,actor_id BIGINT,action TEXT NOT NULL,details JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS sistemas_reports(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,reporter_id BIGINT NOT NULL,target_id BIGINT NOT NULL,reason TEXT NOT NULL,evidence TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS sistemas_suggestions(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),message_id BIGINT)",
  "CREATE TABLE IF NOT EXISTS sistemas_xp(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,xp BIGINT NOT NULL DEFAULT 0,level INTEGER NOT NULL DEFAULT 0,last_message_at TIMESTAMPTZ,PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS nexus_wallets(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,balance BIGINT NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS nexus_economy_tx(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,from_user BIGINT,to_user BIGINT,amount BIGINT NOT NULL,kind TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS nexus_products(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,name TEXT NOT NULL,description TEXT DEFAULT '',price_cents BIGINT NOT NULL,stock INTEGER NOT NULL DEFAULT 0,active BOOLEAN NOT NULL DEFAULT TRUE,category TEXT,created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS nexus_orders(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,product_id BIGINT NOT NULL,qty INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',total_cents BIGINT NOT NULL,payment_ref TEXT,created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS nexus_staff_tasks(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,assignee_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,details TEXT,due_at TIMESTAMPTZ,status TEXT DEFAULT 'open',created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS nexus_events(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,description TEXT,channel_id BIGINT,ends_at TIMESTAMPTZ,status TEXT DEFAULT 'open',created_at TIMESTAMPTZ DEFAULT NOW())",
  "CREATE TABLE IF NOT EXISTS nexus_raffle_entries(event_id BIGINT NOT NULL,user_id BIGINT NOT NULL,PRIMARY KEY(event_id,user_id))",
  "CREATE TABLE IF NOT EXISTS nexus_afk(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,reason TEXT,since TIMESTAMPTZ DEFAULT NOW(),PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS nexus_quarantine(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,moderator_id BIGINT NOT NULL,reason TEXT NOT NULL,expires_at TIMESTAMPTZ,active BOOLEAN DEFAULT TRUE,created_at TIMESTAMPTZ DEFAULT NOW(),released_at TIMESTAMPTZ,release_by BIGINT,PRIMARY KEY(guild_id,user_id))",
  "CREATE TABLE IF NOT EXISTS nexus_invites(guild_id BIGINT NOT NULL,code TEXT NOT NULL,uses INTEGER NOT NULL DEFAULT 0,inviter_id BIGINT,PRIMARY KEY(guild_id,code))",
  "CREATE TABLE IF NOT EXISTS nexus_coupons(guild_id BIGINT NOT NULL,code TEXT NOT NULL,discount_percent INTEGER NOT NULL,active BOOLEAN DEFAULT TRUE,expires_at TIMESTAMPTZ,PRIMARY KEY(guild_id,code))",
  "CREATE TABLE IF NOT EXISTS nexus_announcements(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,channel_id BIGINT NOT NULL,content TEXT NOT NULL,send_at TIMESTAMPTZ NOT NULL,sent BOOLEAN DEFAULT FALSE,created_by BIGINT NOT NULL)"
  ]
  async with self.pool.acquire() as conn:
   async with conn.transaction():
    for q in ddl: await conn.execute(q)
    safe_migrations=["ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS evidence_attachment_url TEXT","ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS occurred TEXT","ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS witnesses TEXT","ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS review_message_id BIGINT","ALTER TABLE sistemas_requests ADD COLUMN IF NOT EXISTS duration_minutes INTEGER","ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS review_message_id BIGINT","ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS decision_reason TEXT",
                "ALTER TABLE sistemas_appeals ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ",
                "ALTER TABLE sistemas_staff ADD COLUMN IF NOT EXISTS role_name TEXT","ALTER TABLE sistemas_suggestions ADD COLUMN IF NOT EXISTS message_id BIGINT"]
    for q in safe_migrations: await conn.execute(q)
    await conn.execute("CREATE INDEX IF NOT EXISTS sistemas_cases_guild_user_idx ON sistemas_cases(guild_id,user_id,id DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS sistemas_audit_guild_idx ON sistemas_audit(guild_id,id DESC)")
    await conn.execute("CREATE INDEX IF NOT EXISTS nexus_quarantine_expiry_idx ON nexus_quarantine(active,expires_at)")
 async def config(self,gid):
  r=await self.pool.fetchrow('SELECT data FROM sistemas_config WHERE guild_id=$1',gid); d=dict(DEFAULTS)
  if r:
   v=r['data']; d.update(json.loads(v) if isinstance(v,str) else dict(v))
  return d
 async def setcfg(self,gid,key,value):
  if key not in DEFAULTS: raise ValueError('Config key not whitelisted')
  d=await self.config(gid); d[key]=value
  await self.pool.execute("INSERT INTO sistemas_config(guild_id,data) VALUES($1,$2::jsonb) ON CONFLICT(guild_id) DO UPDATE SET data=EXCLUDED.data,updated_at=NOW()",gid,json.dumps(d,ensure_ascii=False))
 async def audit(self,guild,actor,action,details,logkey='log_internal_channel_id',color=PURPLE):
  safe={str(k):clip(v,600) for k,v in details.items() if v is not None}
  await self.pool.execute('INSERT INTO sistemas_audit(guild_id,actor_id,action,details) VALUES($1,$2,$3,$4::jsonb)',guild.id,actor,action,json.dumps(safe,ensure_ascii=False))
  cfg=await self.config(guild.id); ch=guild.get_channel(cfg.get(logkey)) if cfg.get(logkey) else None
  if ch:
   e=embed(f'{EMOJI["pin"]} {action}', '\n'.join(f'**{k.replace("_"," ").title()}:** {v}' for k,v in safe.items()),color)
   if cfg.get('theme_image_url') and url_ok(cfg['theme_image_url']): e.set_image(url=cfg['theme_image_url'])
   try: await ch.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
   except discord.HTTPException: log.exception('Falha no log de guild %s',guild.id)
 async def dm(self,user,action,reason,case_id=None,duration=None):
  try:
   e=embed('NEXUS • Registro de moderação',f'**Ação:** {action}\n**Motivo:** {clip(reason,1200)}\n**Registro:** #{case_id or "—"}\n**Duração:** {duration or "Não aplicável"}\n\nSe acredita que houve engano, procure a equipe ou use o canal de apelações configurado.')
   await user.send(embed=e)
  except (discord.Forbidden,discord.HTTPException): log.info('DM indisponível para user id=%s',user.id)
 async def case(self,gid,uid,mid,action,reason,expiry=None):
  return await self.pool.fetchval('INSERT INTO sistemas_cases(guild_id,user_id,moderator_id,action,reason,expires_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',gid,uid,mid,action,reason,expiry)
 async def punish(self,guild,targetid,actor,kind,reason,minutes=None):
  botm=guild.me; target=guild.get_member(targetid); cfg=await self.config(guild.id)
  if target:
   ok,msg=hierarchy(actor,target,botm)
   if not ok: raise ValueError(msg)
  if kind not in ('warn','timeout','mute','kick','ban','hackban','quarentena'): raise ValueError('Tipo de punição inválido')
  expiry=datetime.now(timezone.utc)+timedelta(minutes=minutes) if minutes else None
  if kind in ('timeout','mute'):
   if not target: raise ValueError('Membro não está no servidor')
   if not minutes or minutes<1 or minutes>40320: raise ValueError('Timeout exige duração 1–40320 minutos')
   await target.timeout(timedelta(minutes=minutes),reason=reason)
  elif kind=='kick':
   if not target: raise ValueError('Membro não está no servidor')
   await target.kick(reason=reason)
  elif kind in ('ban','hackban'): await guild.ban(target or discord.Object(id=targetid),reason=reason,delete_message_seconds=0)
  elif kind=='quarentena':
   if not target: raise ValueError('Membro não está no servidor')
   role=guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None
   if not role: raise ValueError('Configure cargo de quarentena em /nexus_config')
   await target.add_roles(role,reason=reason)
   await self.pool.execute('INSERT INTO nexus_quarantine(guild_id,user_id,moderator_id,reason,expires_at,active) VALUES($1,$2,$3,$4,$5,TRUE) ON CONFLICT(guild_id,user_id) DO UPDATE SET moderator_id=EXCLUDED.moderator_id,reason=EXCLUDED.reason,expires_at=EXCLUDED.expires_at,active=TRUE,created_at=NOW()',guild.id,targetid,actor.id,reason,expiry)
  caseid=await self.case(guild.id,targetid,actor.id,kind,reason,expiry)
  try: user=target or await self.bot.fetch_user(targetid)
  except discord.HTTPException: user=None
  if user: await self.dm(user,kind,reason,caseid, f'{minutes} min' if minutes else None)
  await self.audit(guild,actor.id,'Punição aplicada',{'case_id':caseid,'target_id':targetid,'tipo':kind,'motivo':reason,'duration_minutes':minutes},'log_punishment_channel_id',RED)
  return caseid
 async def create_request(self,guild,requester,targetid,kind,reason,occurred='',witnesses=None,evidence=None,minutes=None):
  rid=await self.pool.fetchval('INSERT INTO sistemas_requests(guild_id,requester_id,target_id,kind,reason,occurred,witnesses,evidence_url,duration_minutes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id',guild.id,requester.id,targetid,kind,reason,occurred,witnesses,evidence,minutes)
  cfg=await self.config(guild.id); ch=guild.get_channel(cfg.get('request_channel_id')) if cfg.get('request_channel_id') else None
  if ch:
   e=embed(f'⚖️ Solicitação de punição • #{rid}','Solicitação pendente de análise. IDs persistentes são usados para as ações dos botões.')
   e.add_field(name='Solicitante',value=f'{requester.mention} (`{requester.id}`)',inline=False); e.add_field(name='Alvo',value=f'<@{targetid}> (`{targetid}`)',inline=False); e.add_field(name='Ação',value=kind,inline=True); e.add_field(name='Motivo',value=clip(reason,1000),inline=False); e.add_field(name='Data/ocorrido',value=occurred or '—',inline=True); e.add_field(name='Testemunhas',value=witnesses or '—',inline=True); e.add_field(name='Provas',value=evidence or '—',inline=False)
   msg=await ch.send(embed=e,view=RequestDecisionView(rid),allowed_mentions=discord.AllowedMentions.none()); await self.pool.execute('UPDATE sistemas_requests SET review_message_id=$1 WHERE id=$2',msg.id,rid)
  await self.audit(guild,requester.id,'Solicitação de punição registrada',{'request_id':rid,'target_id':targetid,'kind':kind},'log_internal_channel_id'); return rid
 async def decision(self,inter,rid,status,reason='Decisão registrada'):
  row=await self.pool.fetchrow('SELECT * FROM sistemas_requests WHERE id=$1 AND guild_id=$2 FOR UPDATE',rid,inter.guild.id)
  if not row or row['status']!='pending': return await reply(inter,'Solicitação já decidida ou não encontrada.')
  cfg=await self.config(inter.guild.id)
  if not staff(inter.user,cfg): return await reply(inter,'Sem autorização para revisar solicitações.')
  await self.pool.execute('UPDATE sistemas_requests SET status=$1,reviewer_id=$2,decision_reason=$3,decided_at=NOW() WHERE id=$4 AND status=\'pending\'',status,inter.user.id,reason,rid)
  applied=None
  if status=='approved' and row['kind'] in set(cfg.get('request_auto_types') or []):
   try: applied=await self.punish(inter.guild,row['target_id'],inter.user,row['kind'],row['reason'],row['duration_minutes'])
   except Exception as exc: await reply(inter,f'Aprovado, mas execução falhou: {clip(exc,250)}'); return
  if inter.message and inter.message.embeds:
   e=inter.message.embeds[0]; e.color=GREEN if status=='approved' else RED; e.add_field(name='Decisão',value=f'{status} por {inter.user.mention}\n{reason}',inline=False); e.add_field(name='Aplicação automática',value=f'Caso #{applied}' if applied else 'Não executada (manual/configuração)',inline=False)
   await inter.message.edit(embed=e,view=None)
  await self.audit(inter.guild,inter.user.id,'Solicitação decidida',{'request_id':rid,'status':status,'reason':reason},'log_internal_channel_id'); await reply(inter,'Decisão registrada com sucesso.')
 async def create_appeal(self,inter,caseid,explanation,evidence=None):
  case=await self.pool.fetchrow('SELECT * FROM sistemas_cases WHERE id=$1 AND guild_id=$2 AND user_id=$3',caseid,inter.guild.id,inter.user.id)
  if not case: return await reply(inter,'Punição não encontrada para seu ID neste servidor.')
  aid=await self.pool.fetchval('INSERT INTO sistemas_appeals(guild_id,case_id,appellant_id,explanation,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id',inter.guild.id,caseid,inter.user.id,explanation,evidence)
  cfg=await self.config(inter.guild.id); ch=inter.guild.get_channel(cfg.get('appeal_channel_id')) if cfg.get('appeal_channel_id') else None
  if ch:
   e=embed(f'📨 Apelação • #{aid}',f'Caso de punição #{caseid}'); e.add_field(name='Solicitante',value=f'{inter.user.mention} ({inter.user.id})',inline=False); e.add_field(name='Explicação',value=clip(explanation,1200),inline=False); e.add_field(name='Provas',value=evidence or '—',inline=False)
   m=await ch.send(embed=e,view=AppealDecisionView(aid)); await self.pool.execute('UPDATE sistemas_appeals SET review_message_id=$1 WHERE id=$2',m.id,aid)
  await self.audit(inter.guild,inter.user.id,'Apelação registrada',{'appeal_id':aid,'case_id':caseid},'log_internal_channel_id'); await reply(inter,f'Apelação registrada: **#{aid}**')
 async def appeal_decision(self,inter,aid,status,reason):
  row=await self.pool.fetchrow('SELECT * FROM sistemas_appeals WHERE id=$1 AND guild_id=$2 AND status=\'pending\'',aid,inter.guild.id)
  cfg=await self.config(inter.guild.id)
  if not row: return await reply(inter,'Apelação já decidida ou não encontrada.')
  if not staff(inter.user,cfg): return await reply(inter,'Sem autorização.')
  await self.pool.execute('UPDATE sistemas_appeals SET status=$1,reviewer_id=$2,decision_reason=$3,decided_at=NOW() WHERE id=$4',status,inter.user.id,reason,aid)
  if status=='approved': await self.pool.execute('UPDATE sistemas_cases SET active=FALSE WHERE id=$1 AND guild_id=$2',row['case_id'],inter.guild.id)
  try: u=await self.bot.fetch_user(row['appellant_id']); await u.send(embed=embed('Nexus • Resultado da apelação',f'Apelação **#{aid}**: **{status}**\nJustificativa: {reason}'))
  except discord.HTTPException: pass
  await self.audit(inter.guild,inter.user.id,'Apelação decidida',{'appeal_id':aid,'status':status,'reason':reason},'log_internal_channel_id'); await reply(inter,'Decisão de apelação registrada.')
 async def quarantine_release(self,guild,user_id,actorid,reason):
  cfg=await self.config(guild.id); role=guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None; member=guild.get_member(user_id)
  if member and role: await member.remove_roles(role,reason=reason)
  await self.pool.execute('UPDATE nexus_quarantine SET active=FALSE,released_at=NOW(),release_by=$3 WHERE guild_id=$1 AND user_id=$2 AND active=TRUE',guild.id,user_id,actorid)
  await self.audit(guild,actorid,'Quarentena removida',{'user_id':user_id,'reason':reason},'log_punishment_channel_id',GREEN)
 @tasks.loop(minutes=1)
 async def expiry_loop(self):
  await self.bot.wait_until_ready()
  rows=await self.pool.fetch('SELECT guild_id,user_id FROM nexus_quarantine WHERE active=TRUE AND expires_at<=NOW()')
  for r in rows:
   g=self.bot.get_guild(r['guild_id'])
   if g:
    try: await self.quarantine_release(g,r['user_id'],self.bot.user.id,'Expiração automática')
    except Exception: log.exception('Quarantine expiry failure guild=%s user=%s',g.id,r['user_id'])
  pending=await self.pool.fetch('SELECT id,guild_id,channel_id,content,send_at FROM nexus_announcements WHERE sent=FALSE AND send_at<=NOW()')
  for r in pending:
   g=self.bot.get_guild(r['guild_id']); ch=g.get_channel(r['channel_id']) if g else None
   if ch:
    try: await ch.send(r['content'],allowed_mentions=discord.AllowedMentions.none()); await self.pool.execute('UPDATE nexus_announcements SET sent=TRUE WHERE id=$1',r['id'])
    except discord.HTTPException: log.exception('Scheduled announcement failed id=%s',r['id'])
 @expiry_loop.before_loop
 async def before_expiry(self): await self.bot.wait_until_ready()
 async def backup(self,gid):
  cfg=await self.config(gid); data={"config":cfg}
  for table in ('sistemas_cases','sistemas_requests','sistemas_appeals','sistemas_audit','sistemas_reports','sistemas_suggestions','sistemas_xp','nexus_quarantine','nexus_wallets','nexus_economy_tx'):
   rows=await self.pool.fetch(f'SELECT * FROM {table} WHERE guild_id=$1 ORDER BY 1',gid); data[table]=[{k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in dict(row).items()} for row in rows]
  await self.pool.execute('INSERT INTO sistemas_backups(guild_id,payload) VALUES($1,$2::jsonb)',gid,json.dumps(data,default=str,ensure_ascii=False))
 @tasks.loop(hours=24)
 async def backup_loop(self):
  await self.bot.wait_until_ready()
  for g in self.bot.guilds:
   try: await self.backup(g.id)
   except Exception: log.exception('Backup failed guild=%s',g.id)
 @backup_loop.before_loop
 async def before_backup(self): await self.bot.wait_until_ready()
 # dot-prefix handler for . commands without editing the legacy main.py. Existing ! commands continue.
 @commands.Cog.listener()
 async def on_message(self,msg):
  if msg.author.bot or not msg.guild:return
  cfg=await self.config(msg.guild.id)
  # Anti-automod: alert/actions configured via safe toggles. Deletions logged, no punitive automation.
  links=bool(re.search(r'https?://|discord\.gg/|discord\.com/invite/',msg.content,re.I))
  invites=bool(re.search(r'discord\.gg/|discord\.com/invite/',msg.content,re.I))
  words=[str(w).lower() for w in (cfg.get('filter_words') or [])]
  violation=(cfg.get('anti_links_enabled') and links) or (cfg.get('anti_invites_enabled') and invites) or any(w and w in msg.content.lower() for w in words) or len(msg.mentions)+len(msg.role_mentions)>int(cfg.get('max_mentions',5))
  if violation:
   try: await msg.delete()
   except discord.HTTPException: pass
   await self.audit(msg.guild,msg.author.id,'AutoMod: mensagem removida',{'channel_id':msg.channel.id,'message_id':msg.id,'type':'filter'},'log_internal_channel_id',GOLD)
   return
  if cfg.get('anti_spam_enabled'):
   q=self.msg_windows[(msg.guild.id,msg.author.id)]; now=time.monotonic(); q.append((now,msg.content))
   while q and now-q[0][0]>int(cfg.get('spam_window',8)):q.popleft()
   repeated=len(q)>=int(cfg.get('spam_count',5)) and len({x[1] for x in q})<=2
   if len(q)>=int(cfg.get('spam_count',5)) or repeated:
    try: await msg.delete()
    except discord.HTTPException: pass
    await self.audit(msg.guild,msg.author.id,'AutoMod: spam/flood',{'channel_id':msg.channel.id,'count':len(q)},'log_internal_channel_id',GOLD); q.clear(); return
  # AFK mentions and return
  for m in msg.mentions:
   row=await self.pool.fetchrow('SELECT reason,since FROM nexus_afk WHERE guild_id=$1 AND user_id=$2',msg.guild.id,m.id)
   if row:
    await msg.reply(embed=embed('AFK • Membro ausente',f'{m.mention} está ausente: {clip(row["reason"] or "Sem motivo",250)}'),delete_after=12)
  afk=await self.pool.fetchrow('SELECT reason FROM nexus_afk WHERE guild_id=$1 AND user_id=$2',msg.guild.id,msg.author.id)
  if afk:
   await self.pool.execute('DELETE FROM nexus_afk WHERE guild_id=$1 AND user_id=$2',msg.guild.id,msg.author.id)
   await msg.reply(embed=embed('Bem-vindo de volta!',f'{msg.author.mention}, seu status AFK foi removido.'),delete_after=10)
  # XP, cooldown persisted.
  if cfg.get('xp_enabled'):
   row=await self.pool.fetchrow('SELECT xp,level,last_message_at FROM sistemas_xp WHERE guild_id=$1 AND user_id=$2',msg.guild.id,msg.author.id)
   if not row or not row['last_message_at'] or (datetime.now(timezone.utc)-row['last_message_at']).total_seconds()>=int(cfg.get('xp_cooldown',60)):
    add=5; xp=(row['xp'] if row else 0)+add; level=int(xp**0.5//5)
    await self.pool.execute('INSERT INTO sistemas_xp(guild_id,user_id,xp,level,last_message_at) VALUES($1,$2,$3,$4,NOW()) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=EXCLUDED.xp,level=EXCLUDED.level,last_message_at=NOW()',msg.guild.id,msg.author.id,xp,level)
    if row and level>row['level']: await msg.channel.send(embed=embed('✨ Level up!',f'{msg.author.mention} alcançou o nível **{level}**!'),delete_after=12)
  if msg.content.startswith('.'):
   raw=msg.content[1:].strip(); name=raw.split(maxsplit=1)[0].lower() if raw else ''
   if name in ('nexus','painelnexus','painel'): await self.send_public_panel(msg.channel,msg.author)
   elif name=='afk': await self.afk_prefix_action(msg,raw[4:].strip() or 'Ausente')
   elif name=='afk_sair':
    vc=msg.guild.voice_client
    if vc: await vc.disconnect(force=True); await msg.reply('Bot saiu da call.')
   elif name=='mod' and staff(msg.author,cfg): await msg.reply(embed=self.moderation_menu(msg.guild))
   elif name=='logs' and staff(msg.author,cfg): await self.logs_prefix(msg,int(raw.split()[1]) if len(raw.split())>1 and raw.split()[1].isdigit() else 10)
   elif name=='quarentena' and staff(msg.author,cfg):
    args=raw.split(maxsplit=2)
    if len(args)>=2 and args[1].isdigit():
     targetid=int(args[1]); reason=args[2] if len(args)>2 else 'Quarentena aplicada pela equipe'
     try: caseid=await self.punish(msg.guild,targetid,msg.author,'quarentena',reason,None); await msg.reply(f'Quarentena aplicada. Caso #{caseid}')
     except Exception as ex: await msg.reply(f'Falhou: {clip(ex,250)}')
   elif name in ('ban','kick','warn','mute','hackban'):
    args=raw.split(maxsplit=3)
    if len(args)>=2:
     uidmatch=re.search(r'\d{15,22}',args[1]);targetid=int(uidmatch.group()) if uidmatch else 0
     duration=None;reason='Sem motivo informado'
     if name=='mute' and len(args)>=3 and args[2].isdigit():duration=int(args[2]);reason=args[3] if len(args)>3 else reason
     elif len(args)>=3:reason=args[2]+' '+(args[3] if len(args)>3 else '')
     required={'ban':'ban_members','hackban':'ban_members','kick':'kick_members','mute':'moderate_members','warn':'moderate_members'}[name]
     if targetid:
      if not staff(msg.author,cfg) and not getattr(msg.author.guild_permissions,required,False): await msg.reply('Sem permissão para essa punição.')
      else:
       try: caseid=await self.punish(msg.guild,targetid,msg.author,'timeout' if name=='mute' else name,reason.strip(),duration); await msg.reply(f'Punição aplicada e registrada no caso #{caseid}.')
       except Exception as ex: await msg.reply(f'Falha: {clip(ex,250)}')
   elif name=='liberar' and staff(msg.author,cfg):
    args=raw.split(maxsplit=2)
    if len(args)>1 and args[1].isdigit(): await self.quarantine_release(msg.guild,int(args[1]),msg.author.id,args[2] if len(args)>2 else 'Liberação manual'); await msg.reply('Liberação processada.')
   elif name=='wallet': await msg.reply(embed=await self.wallet_embed(msg.guild,msg.author.id))
   elif name=='daily': await self.daily(msg.guild,msg.author)
   elif name=='work': await self.work(msg.guild,msg.author)
   elif name=='pay': await self.pay_prefix(msg)
   elif name=='rank': await self.rank_prefix(msg)
   elif name=='shop': await self.shop_prefix(msg)
   elif name=='help': await msg.reply(embed=self.help_embed())
 async def afk_prefix_action(self,msg,reason):
  member=msg.author
  if not member.voice or not member.voice.channel: return await msg.reply('Entre em um canal de voz primeiro para usar AFK call.')
  vc=msg.guild.voice_client
  if vc: await vc.move_to(member.voice.channel)
  else: await member.voice.channel.connect(self_deaf=True,self_mute=True)
  await self.pool.execute('INSERT INTO nexus_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()',msg.guild.id,member.id,reason)
  await msg.reply(f'AFK ativado; bot na call **{member.voice.channel.name}**. Use `.afk_sair` para desconectar.')
 async def send_public_panel(self,channel,author):
  cfg=await self.config(channel.guild.id)
  e=embed('NEXUS • CENTRAL DE SISTEMAS','Uma central organizada de utilidades, comunidade e administração.\n\n**Moderação:** denúncias, punições, revisão e histórico.\n**Comunidade:** sugestões, XP, eventos e sorteios.\n**Economia:** carteira, diário, trabalho e transferências.\n**Equipe:** tarefas, status e acompanhamento.\n**Segurança:** automod, anti-raid, anti-nuke e quarentena.\n\nUse os comandos `.help` ou `/nexus` para acessar as ferramentas.',PURPLE)
  e.set_thumbnail(url=VISUALS['shield']); e.set_image(url=cfg.get('theme_image_url') or VISUALS['banner']); await channel.send(embed=e,view=NexusPublicPanel())
 def moderation_menu(self,guild):
  e=embed('NEXUS • MODERAÇÃO','Comandos: `.ban @membro motivo`, `.kick @membro motivo`, `.warn @membro motivo` (slash), `.mute @membro minutos motivo`, `.quarentena ID motivo`, `.liberar ID motivo`, `.logs [limite]`.'); return e
 async def logs_prefix(self,msg,limit):
  rows=await self.pool.fetch('SELECT id,actor_id,action,details,created_at FROM sistemas_audit WHERE guild_id=$1 ORDER BY id DESC LIMIT $2',msg.guild.id,max(1,min(20,limit))); e=embed('NEXUS • AUDITORIA',f'{len(rows)} registros recentes')
  for r in rows:
   d=r['details'] if isinstance(r['details'],dict) else json.loads(r['details'] or '{}'); e.add_field(name=f'#{r["id"]} {r["action"]}',value=clip(f'Autor: <@{r["actor_id"]}>\n{d}\n<t:{int(r["created_at"].timestamp())}:R>',850),inline=False)
  await msg.reply(embed=e)
 async def wallet_embed(self,guild,uid):
  bal=await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2',guild.id,uid) or 0; return embed('NEXUS • CARTEIRA',f'<@{uid}> possui **{bal:,} NXC** na economia virtual.\n\nEconomia virtual não representa dinheiro real e não tem conversão ou pagamento externo.')
 async def ensure_wallet(self,gid,uid): await self.pool.execute('INSERT INTO nexus_wallets(guild_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING',gid,uid)
 async def daily(self,guild,user):
  await self.ensure_wallet(guild.id,user.id)
  # Transactional cooldown via advisory lock + persisted ledger; daily key represented as kind + UTC date.
  async with self.pool.acquire() as c:
   async with c.transaction():
    await c.execute('SELECT pg_advisory_xact_lock($1)',user.id)
    exists=await c.fetchval("SELECT 1 FROM nexus_economy_tx WHERE guild_id=$1 AND to_user=$2 AND kind=$3 AND created_at >= date_trunc('day',NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",guild.id,user.id,'daily')
    if exists:
     try: await user.send('Você já recebeu seu diário hoje.')
     except discord.HTTPException: pass
     return
    amt=int((await self.config(guild.id)).get('economy_daily',100)); await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2',guild.id,user.id,amt); await c.execute('INSERT INTO nexus_economy_tx(guild_id,to_user,amount,kind) VALUES($1,$2,$3,$4)',guild.id,user.id,amt,'daily')
  try: await user.send(embed=embed('NEXUS • Recompensa diária',f'Você recebeu **{amt} NXC**.'))
  except discord.HTTPException: pass
 async def work(self,guild,user):
  await self.ensure_wallet(guild.id,user.id)
  async with self.pool.acquire() as c:
   async with c.transaction():
    await c.execute('SELECT pg_advisory_xact_lock($1)',user.id)
    cooldown=int((await self.config(guild.id)).get('economy_cooldown',3600)); recent=await c.fetchval("SELECT 1 FROM nexus_economy_tx WHERE guild_id=$1 AND to_user=$2 AND kind='work' AND created_at>NOW()-($3 * INTERVAL '1 second')",guild.id,user.id,cooldown)
    if recent:
     try: await user.send(f'Trabalho em cooldown; aguarde {cooldown//60} minutos.')
     except discord.HTTPException: pass
     return
    cfg=await self.config(guild.id); amount=__import__('random').randint(int(cfg.get('economy_work_min',25)),int(cfg.get('economy_work_max',100))); await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2',guild.id,user.id,amount); await c.execute('INSERT INTO nexus_economy_tx(guild_id,to_user,amount,kind) VALUES($1,$2,$3,$4)',guild.id,user.id,amount,'work')
  try: await user.send(embed=embed('NEXUS • Trabalho',f'Você recebeu **{amount} NXC** por seu trabalho.'))
  except discord.HTTPException: pass
 async def pay_prefix(self,msg):
  parts=msg.content.split()
  if len(parts)<3 or not parts[1].isdigit() or not parts[2].isdigit(): return await msg.reply('Uso: `.pay ID quantidade`')
  uid,amount=int(parts[1]),int(parts[2]); gid=msg.guild.id
  if uid==msg.author.id or amount<=0: return await msg.reply('Destino/valor inválido.')
  await self.ensure_wallet(gid,msg.author.id); await self.ensure_wallet(gid,uid)
  async with self.pool.acquire() as c:
   async with c.transaction():
    await c.execute('SELECT pg_advisory_xact_lock($1)',msg.author.id)
    bal=await c.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE',gid,msg.author.id)
    if bal<amount:return await msg.reply('Saldo insuficiente.')
    await c.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2',gid,msg.author.id,amount); await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2',gid,uid,amount); await c.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$3,$4,$5)',gid,msg.author.id,uid,amount,'transfer')
  await msg.reply(f'Transferência de **{amount} NXC** para <@{uid}> concluída.')
 async def rank_prefix(self,msg):
  rows=await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10',msg.guild.id); e=embed('NEXUS • RANKING XP','Top 10 membros')
  for i,r in enumerate(rows,1):e.add_field(name=f'{i}. <@{r["user_id"]}>',value=f'{r["xp"]} XP • nível {r["level"]}',inline=False)
  await msg.reply(embed=e)
 async def shop_prefix(self,msg):
  rows=await self.pool.fetch('SELECT id,name,description,price_cents,stock FROM nexus_products WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 20',msg.guild.id); e=embed('NEXUS • LOJA', 'Produtos digitais/físicos configurados. Pagamentos externos não são habilitados sem credenciais e confirmação segura de provedor.')
  for r in rows:e.add_field(name=f'#{r["id"]} • {r["name"]} • R$ {r["price_cents"]/100:.2f}',value=f'{clip(r["description"],200)}\nEstoque: {r["stock"]}',inline=False)
  await msg.reply(embed=e)
 def help_embed(self):
  e=embed('NEXUS • COMANDOS', 'Prefixo principal para novos comandos: `.`. Comandos legados do ticket permanecem com `!` e slash.')
  e.add_field(name='Comunidade',value='`.nexus` • `.help` • `.rank` • `.suggest` (slash) • `/denunciar`',inline=False)
  e.add_field(name='Economia',value='`.wallet` • `.daily` • `.work` • `.pay ID valor` • `.shop`',inline=False)
  e.add_field(name='Moderação',value='`.mod` • `.quarentena ID motivo` • `.liberar ID motivo` • `.logs` • slash de punição',inline=False)
  e.add_field(name='AFK Call',value='`.afk motivo` (entra bot na call) • `.afk_sair`',inline=False); return e

 # Slash command group dashboard/config
 @app_commands.command(name='nexus',description='Abre o painel interativo Nexus.')
 async def nexus_cmd(self,inter): await inter.response.send_message(embed=embed('NEXUS • CENTRAL','Escolha a categoria pelos botões abaixo. Ações administrativas exigem autorização.'),view=NexusPublicPanel(),ephemeral=True)
 @app_commands.command(name='nexus_config',description='Configuração segura do Nexus para este servidor.')
 @app_commands.checks.has_permissions(administrator=True)
 async def nexus_config(self,inter,staff_role:Optional[discord.Role]=None,quarantine_role:Optional[discord.Role]=None,request_channel:Optional[discord.TextChannel]=None,appeal_channel:Optional[discord.TextChannel]=None,report_channel:Optional[discord.TextChannel]=None,suggestion_channel:Optional[discord.TextChannel]=None,remote_admin_ids:str=''):
  if staff_role:
   cfg=await self.config(inter.guild.id); roles=set(cfg.get('staff_role_ids') or []);roles.add(staff_role.id);await self.setcfg(inter.guild.id,'staff_role_ids',sorted(roles))
  if quarantine_role:await self.setcfg(inter.guild.id,'quarantine_role_id',quarantine_role.id)
  for k,v in [('request_channel_id',request_channel),('appeal_channel_id',appeal_channel),('report_channel_id',report_channel),('suggestion_channel_id',suggestion_channel)]:
   if v: await self.setcfg(inter.guild.id,k,v.id)
  ids=[]
  if remote_admin_ids.strip():
   try: ids=[int(x.strip()) for x in remote_admin_ids.split(',') if x.strip().isdigit()]
   except ValueError: return await reply(inter,'IDs remotos inválidos.')
   await self.setcfg(inter.guild.id,'remote_admin_ids',ids); await self.setcfg(inter.guild.id,'remote_enabled',bool(ids))
  await self.audit(inter.guild,inter.user.id,'Configuração Nexus atualizada',{'staff_role':staff_role.id if staff_role else None,'quarantine_role':quarantine_role.id if quarantine_role else None,'remote_ids':ids},'log_internal_channel_id')
  await reply(inter,'Configurações aplicadas. Use `/nexus_config_logs` para ajustar os logs preservados.')
 @app_commands.command(name='nexus_config_logs',description='Configura canais de log por categoria.')
 @app_commands.checks.has_permissions(administrator=True)
 async def config_logs(self,inter,server_log:Optional[discord.TextChannel]=None,member_log:Optional[discord.TextChannel]=None,role_log:Optional[discord.TextChannel]=None,punishment_log:Optional[discord.TextChannel]=None,internal_log:Optional[discord.TextChannel]=None):
  for k,v in [('log_server_channel_id',server_log),('log_member_channel_id',member_log),('log_role_channel_id',role_log),('log_punishment_channel_id',punishment_log),('log_internal_channel_id',internal_log)]:
   if v: await self.setcfg(inter.guild.id,k,v.id)
  await reply(inter,'Canais de logs atualizados (sistema de logs preservado e configurável).')
 @app_commands.command(name='painel_remoto',description='Painel remoto de controle dos servidores Nexus (somente IDs autorizados).')
 async def remote_panel(self,inter):
  allowed=set(int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS','').split(',') if x.strip().isdigit())
  if inter.user.id not in allowed:return await reply(inter,'Acesso remoto negado. ID não autorizado na variável NEXUS_REMOTE_ADMIN_IDS.')
  await inter.response.send_message(embed=embed('NEXUS • REMOTE OPS',f'Servidores conectados: **{len(self.bot.guilds)}**\nSelecione uma ação abaixo.'),view=NexusRemotePanel(),ephemeral=True)
 @app_commands.command(name='punir',description='Aplicar punição com motivo e validação de hierarquia.')
 async def punish_cmd(self,inter,kind:str,user_id:str,reason:str,minutes:Optional[app_commands.Range[int,1,40320]]=None):
  cfg=await self.config(inter.guild.id); perms={'ban':'ban_members','hackban':'ban_members','kick':'kick_members','mute':'moderate_members','timeout':'moderate_members','warn':'moderate_members','quarentena':'manage_roles'}
  if not staff(inter.user,cfg) and not getattr(inter.user.guild_permissions,perms.get(kind,'moderate_members'),False):return await reply(inter,'Você não tem autorização para essa ação.')
  if not user_id.isdigit():return await reply(inter,'ID de usuário inválido.')
  try: caseid=await self.punish(inter.guild,int(user_id),inter.user,kind,reason,minutes)
  except Exception as ex:return await reply(inter,f'Não foi possível aplicar: {clip(ex,300)}')
  await reply(inter,f'{kind} executado e registrado. Caso **#{caseid}**.')
 @app_commands.command(name='historico_punicoes',description='Consultar histórico de punições.')
 async def history_cmd(self,inter,user:discord.User):
  cfg=await self.config(inter.guild.id)
  if not staff(inter.user,cfg):return await reply(inter,'Somente equipe autorizada.')
  rows=await self.pool.fetch('SELECT id,action,reason,moderator_id,created_at,active,expires_at FROM sistemas_cases WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 15',inter.guild.id,user.id); e=embed(f'NEXUS • HISTÓRICO {user}',f'{len(rows)} registros encontrados')
  for r in rows:e.add_field(name=f'Caso #{r["id"]} • {r["action"]} • {"ativo" if r["active"] else "inativo"}',value=clip(f'{r["reason"]}\nMod: <@{r["moderator_id"]}> • <t:{int(r["created_at"].timestamp())}:R>',700),inline=False)
  await reply(inter,em=e)
 @app_commands.command(name='quarentena_lista',description='Listar usuários em quarentena.')
 async def quarantine_list(self,inter):
  cfg=await self.config(inter.guild.id)
  if not staff(inter.user,cfg):return await reply(inter,'Sem autorização.')
  rows=await self.pool.fetch('SELECT user_id,reason,moderator_id,expires_at,created_at FROM nexus_quarantine WHERE guild_id=$1 AND active=TRUE ORDER BY created_at DESC LIMIT 30',inter.guild.id);e=embed('NEXUS • QUARENTENA',f'{len(rows)} registros ativos')
  for r in rows:e.add_field(name=f'<@{r["user_id"]}>',value=f'Motivo: {clip(r["reason"],250)}\nResponsável: <@{r["moderator_id"]}>\nExpira: {r["expires_at"] or "Sem prazo"}',inline=False)
  await reply(inter,em=e)
 @app_commands.command(name='afk',description='Ativa status AFK e conecta o bot à sua call atual.')
 async def afk_slash(self,inter,reason:str='Ausente'):
  if not inter.user.voice or not inter.user.voice.channel:return await reply(inter,'Entre em uma call primeiro.')
  try:
   vc=inter.guild.voice_client
   if vc: await vc.move_to(inter.user.voice.channel)
   else: await inter.user.voice.channel.connect(self_deaf=True,self_mute=True)
   await self.pool.execute('INSERT INTO nexus_afk(guild_id,user_id,reason) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=EXCLUDED.reason,since=NOW()',inter.guild.id,inter.user.id,reason)
   await reply(inter,f'Bot conectado a **{inter.user.voice.channel.name}** até comando de saída.')
  except discord.HTTPException as e:await reply(inter,f'Falha de voz: {clip(e,200)}')
 @app_commands.command(name='afk_sair',description='Desconecta o bot da call AFK.')
 async def afk_leave_slash(self,inter):
  vc=inter.guild.voice_client
  if not vc:return await reply(inter,'Bot não está conectado.')
  await vc.disconnect(force=True);await reply(inter,'Desconectado da call.')
 @app_commands.command(name='denunciar',description='Enviar denúncia para a equipe.')
 async def report_slash(self,inter,target:discord.User,reason:str,evidence:Optional[str]=None):
  if evidence and not url_ok(evidence):return await reply(inter,'URL inválida.')
  cfg=await self.config(inter.guild.id);ch=inter.guild.get_channel(cfg.get('report_channel_id')) if cfg.get('report_channel_id') else None
  if not ch:return await reply(inter,'Canal de denúncias não configurado por `/nexus_config`.')
  rid=await self.pool.fetchval('INSERT INTO sistemas_reports(guild_id,reporter_id,target_id,reason,evidence) VALUES($1,$2,$3,$4,$5) RETURNING id',inter.guild.id,inter.user.id,target.id,reason,evidence)
  e=embed(f'NEXUS • DENÚNCIA #{rid}','Registro recebido para análise.');e.add_field(name='Autor',value=f'{inter.user} ({inter.user.id})');e.add_field(name='Alvo',value=f'{target} ({target.id})');e.add_field(name='Relato',value=clip(reason,1000));e.add_field(name='Provas',value=evidence or '—');await ch.send(embed=e,allowed_mentions=discord.AllowedMentions.none());await self.audit(inter.guild,inter.user.id,'Denúncia registrada',{'report_id':rid,'target_id':target.id});await reply(inter,f'Denúncia enviada. Protocolo #{rid}.')
 @app_commands.command(name='sugerir',description='Enviar sugestão comunitária.')
 async def suggest_slash(self,inter,suggestion:str):
  cfg=await self.config(inter.guild.id);ch=inter.guild.get_channel(cfg.get('suggestion_channel_id')) if cfg.get('suggestion_channel_id') else None
  if not ch:return await reply(inter,'Configure o canal de sugestões em `/nexus_config`.')
  sid=await self.pool.fetchval('INSERT INTO sistemas_suggestions(guild_id,user_id,content) VALUES($1,$2,$3) RETURNING id',inter.guild.id,inter.user.id,suggestion);e=embed(f'💡 NEXUS • SUGESTÃO #{sid}',clip(suggestion,3000));e.add_field(name='Autor',value=inter.user.mention);m=await ch.send(embed=e);await m.add_reaction('👍');await m.add_reaction('👎');await self.pool.execute('UPDATE sistemas_suggestions SET message_id=$1 WHERE id=$2',m.id,sid);await reply(inter,f'Sugestão registrada #{sid}.')
 @app_commands.command(name='ranking_xp',description='Mostrar ranking XP da comunidade.')
 async def xp_rank_slash(self,inter):
  rows=await self.pool.fetch('SELECT user_id,xp,level FROM sistemas_xp WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10',inter.guild.id);e=embed('NEXUS • RANK XP','Top 10')
  for i,r in enumerate(rows,1):e.add_field(name=f'{i}º • <@{r["user_id"]}>',value=f'{r["xp"]} XP • nível {r["level"]}',inline=False)
  await reply(inter,em=e)
 @app_commands.command(name='solicitar_punicao',description='Enviar pedido de punição para revisão da equipe.')
 async def request_slash(self,inter,target:discord.User,kind:str,reason:str,occurred:str='',witnesses:str='',evidence:str='',minutes:Optional[app_commands.Range[int,1,40320]]=None):
  cfg=await self.config(inter.guild.id)
  if not staff(inter.user,cfg):return await reply(inter,'Somente staff autorizada pode solicitar punições.')
  allowed={'warn','timeout','mute','kick','ban','hackban','quarentena'}
  if kind not in allowed:return await reply(inter,'Tipo inválido. Use warn, timeout, mute, kick, ban, hackban ou quarentena.')
  if kind in ('timeout','mute') and not minutes:return await reply(inter,'Timeout/mute precisa de duração (minutos).')
  if evidence and not url_ok(evidence):return await reply(inter,'Link de prova deve ser URL http(s).')
  rid=await self.create_request(inter.guild,inter.user,target.id,kind,reason,occurred,witnesses or None,evidence or None,minutes)
  await reply(inter,f'Solicitação enviada para análise: **#{rid}**.')
 @app_commands.command(name='apelar_punicao',description='Solicitar revisão de uma punição aplicada ao seu usuário.')
 async def appeal_slash(self,inter,case_id:int,explanation:str,evidence:str=''):
  if evidence and not url_ok(evidence):return await reply(inter,'URL de prova inválida.')
  await self.create_appeal(inter,case_id,explanation,evidence or None)
 @app_commands.command(name='quarentena_liberar',description='Liberar usuário da quarentena.')
 async def quarantine_release_slash(self,inter,user:discord.User,reason:str='Liberação manual'):
  cfg=await self.config(inter.guild.id)
  if not staff(inter.user,cfg):return await reply(inter,'Sem autorização para liberar quarentena.')
  await self.quarantine_release(inter.guild,user.id,inter.user.id,reason);await reply(inter,'Liberação concluída e registrada.')
 @app_commands.command(name='automod_config',description='Configurar automod, links, convites, spam e palavras proibidas.')
 @app_commands.checks.has_permissions(administrator=True)
 async def automod_config(self,inter,spam:bool=False,links:bool=False,invites:bool=False,words:str='',mention_limit:app_commands.Range[int,2,20]=5):
  await self.setcfg(inter.guild.id,'anti_spam_enabled',spam);await self.setcfg(inter.guild.id,'anti_links_enabled',links);await self.setcfg(inter.guild.id,'anti_invites_enabled',invites);await self.setcfg(inter.guild.id,'filter_words',[w.strip().lower() for w in words.split('|') if w.strip()][:100]);await self.setcfg(inter.guild.id,'max_mentions',mention_limit)
  await self.audit(inter.guild,inter.user.id,'Automod configurado',{'spam':spam,'links':links,'invites':invites,'filter_word_count':len(words.split('|')),'mention_limit':mention_limit});await reply(inter,'AutoMod atualizado. Remoções são registradas; punições automáticas não estão ativadas por padrão.')
 @app_commands.command(name='config_protecao',description='Configurar alerta Anti-Raid/Anti-Nuke, limiares e IDs confiáveis.')
 @app_commands.checks.has_permissions(administrator=True)
 async def protection_config(self,inter,anti_raid:bool=False,anti_nuke:bool=False,raid_threshold:app_commands.Range[int,3,30]=6,window_seconds:app_commands.Range[int,5,60]=12,trusted_ids:str=''):
  await self.setcfg(inter.guild.id,'anti_raid_enabled',anti_raid);await self.setcfg(inter.guild.id,'anti_nuke_enabled',anti_nuke);await self.setcfg(inter.guild.id,'anti_raid_threshold',raid_threshold);await self.setcfg(inter.guild.id,'anti_raid_window_seconds',window_seconds)
  ids=[int(x.strip()) for x in trusted_ids.split(',') if x.strip().isdigit()][:100];await self.setcfg(inter.guild.id,'trusted_admin_ids',ids);await self.audit(inter.guild,inter.user.id,'Proteções configuradas',{'anti_raid':anti_raid,'anti_nuke':anti_nuke,'threshold':raid_threshold,'window':window_seconds,'trusted_ids':ids});await reply(inter,'Configurações de proteção salvas. Proteções geram alertas; não executam ações destrutivas automáticas.')
 @app_commands.command(name='backup_manual',description='Criar backup JSON persistente do estado administrativo.')
 @app_commands.checks.has_permissions(administrator=True)
 async def backup_manual_cmd(self,inter):
  await self.backup(inter.guild.id);await reply(inter,'Backup criado no banco. Não contém tokens nem credenciais.')
 @app_commands.command(name='status_nexus',description='Status do bot, banco e módulos.')
 async def status_cmd(self,inter):
  cfg=await self.config(inter.guild.id); e=embed('NEXUS • STATUS',f'Uptime: <t:{int(datetime.now(timezone.utc).timestamp()-(time.monotonic()-self.started))}:R>\nLatência: **{self.bot.latency*1000:.0f} ms**\nServidores: **{len(self.bot.guilds)}**\nMódulo Systems: **ativo**\nDB pool: **conectado** (consulta de teste abaixo)')
  try:await self.pool.fetchval('SELECT 1');e.add_field(name='Banco',value='PostgreSQL conectado',inline=False)
  except Exception:e.add_field(name='Banco',value='Falha de conexão',inline=False)
  await reply(inter,em=e)
 @commands.Cog.listener()
 async def on_member_join(self,member):
  cfg=await self.config(member.guild.id)
  if cfg.get('anti_raid_enabled'):
   q=self.join_windows[member.guild.id];now=time.monotonic();q.append(now);win=int(cfg.get('anti_raid_window_seconds',12))
   while q and now-q[0]>win:q.popleft()
   if len(q)>=int(cfg.get('anti_raid_threshold',6)):
    await self.audit(member.guild,None,'Alerta Anti-Raid',{'join_count':len(q),'window_seconds':win,'last_member_id':member.id},'log_internal_channel_id',RED);q.clear()
  await self.audit(member.guild,None,'Membro entrou',{'user_id':member.id,'account_created':member.created_at.isoformat()},'log_member_channel_id')
  wc=member.guild.get_channel(cfg.get('welcome_channel_id')) if cfg.get('welcome_channel_id') else None
  if wc:
   text=str(cfg.get('welcome_message') or 'Bem-vindo {member} ao {server}').replace('{member}',member.mention).replace('{server}',member.guild.name);e=embed('NEXUS • BOAS-VINDAS',text);e.set_thumbnail(url=member.display_avatar.url);await wc.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
  role=member.guild.get_role(cfg.get('autorole_id')) if cfg.get('autorole_id') else None
  if role:
   try:await member.add_roles(role,reason='Autorole Nexus')
   except discord.HTTPException:log.warning('Autorole failed guild=%s member=%s',member.guild.id,member.id)
 @commands.Cog.listener()
 async def on_member_remove(self,member): await self.audit(member.guild,None,'Membro saiu',{'user_id':member.id,'name':str(member)},'log_member_channel_id')
 @commands.Cog.listener()
 async def on_member_ban(self,guild,user): await self.audit(guild,None,'Ban registrado pelo Discord',{'user_id':user.id},'log_punishment_channel_id',RED)
 @commands.Cog.listener()
 async def on_member_unban(self,guild,user): await self.audit(guild,None,'Desbanimento registrado',{'user_id':user.id},'log_punishment_channel_id',GREEN)
 @commands.Cog.listener()
 async def on_guild_channel_delete(self,ch):
  cfg=await self.config(ch.guild.id); actor=None
  try:
   async for entry in ch.guild.audit_logs(limit=5,action=discord.AuditLogAction.channel_delete):
    if getattr(entry.target,'id',None)==ch.id and (datetime.now(timezone.utc)-entry.created_at).total_seconds()<25:actor=entry.user.id;break
  except discord.HTTPException:pass
  if cfg.get('anti_nuke_enabled') and actor and actor not in cfg.get('trusted_admin_ids',[]) and actor!=self.bot.user.id:await self.audit(ch.guild,actor,'ALERTA ANTI-NUKE • canal excluído',{'channel':ch.name,'channel_id':ch.id},'log_internal_channel_id',RED)
  await self.audit(ch.guild,actor,'Canal excluído',{'channel':ch.name,'channel_id':ch.id},'log_server_channel_id',RED)
 @commands.Cog.listener()
 async def on_guild_role_delete(self,role):
  cfg=await self.config(role.guild.id);actor=None
  try:
   async for entry in role.guild.audit_logs(limit=5,action=discord.AuditLogAction.role_delete):
    if getattr(entry.target,'id',None)==role.id and (datetime.now(timezone.utc)-entry.created_at).total_seconds()<25:actor=entry.user.id;break
  except discord.HTTPException:pass
  if cfg.get('anti_nuke_enabled') and actor and actor not in cfg.get('trusted_admin_ids',[]) and actor!=self.bot.user.id:await self.audit(role.guild,actor,'ALERTA ANTI-NUKE • cargo excluído',{'role':role.name,'role_id':role.id},'log_internal_channel_id',RED)
  await self.audit(role.guild,actor,'Cargo excluído',{'role':role.name,'role_id':role.id},'log_role_channel_id',RED)
 @commands.Cog.listener()
 async def on_guild_channel_create(self,ch):
  cfg=await self.config(ch.guild.id);role=ch.guild.get_role(cfg.get('quarantine_role_id')) if cfg.get('quarantine_role_id') else None
  if role:
   try:await ch.set_permissions(role,view_channel=False,send_messages=False,connect=False,reason='Nexus quarantine role restriction')
   except discord.HTTPException:log.warning('Could not apply quarantine overwrite on new channel %s',ch.id)
  await self.audit(ch.guild,None,'Canal criado',{'channel':ch.name,'channel_id':ch.id},'log_server_channel_id')
 @commands.Cog.listener()
 async def on_guild_role_create(self,role): await self.audit(role.guild,None,'Cargo criado',{'role':role.name,'role_id':role.id},'log_role_channel_id')
 @commands.Cog.listener()
 async def on_guild_role_update(self,before,after):
  changes={a:f'{getattr(before,a,None)} -> {getattr(after,a,None)}' for a in ('name','permissions','position','colour','hoist','mentionable') if getattr(before,a,None)!=getattr(after,a,None)}
  if changes:await self.audit(after.guild,None,'Cargo alterado',{'role':after.name,**changes},'log_role_channel_id')
 @commands.Cog.listener()
 async def on_guild_channel_update(self,before,after):
  changes={a:f'{getattr(before,a,None)} -> {getattr(after,a,None)}' for a in ('name','topic','slowmode_delay','nsfw','category_id') if getattr(before,a,None)!=getattr(after,a,None)}
  if changes:await self.audit(after.guild,None,'Canal alterado',{'channel':after.name,**changes},'log_server_channel_id')
 @commands.Cog.listener()
 async def on_message_delete(self,msg):
  if msg.guild and not msg.author.bot:await self.audit(msg.guild,None,'Mensagem excluída',{'author_id':msg.author.id,'channel_id':msg.channel.id,'content':clip(msg.content,500)},'log_server_channel_id',GOLD)
 @commands.Cog.listener()
 async def on_message_edit(self,before,after):
  if before.guild and before.content!=after.content and not before.author.bot:await self.audit(before.guild,before.author.id,'Mensagem editada',{'channel_id':before.channel.id,'before':clip(before.content,400),'after':clip(after.content,400)},'log_server_channel_id')
 @commands.Cog.listener()
 async def on_voice_state_update(self,member,before,after):
  cfg=await self.config(member.guild.id);trigger_id=cfg.get('temp_voice_trigger_id')
  if after.channel and trigger_id and after.channel.id==trigger_id and (before.channel is None or before.channel.id!=trigger_id):
   category=member.guild.get_channel(cfg.get('temp_voice_category_id')) if cfg.get('temp_voice_category_id') else after.channel.category
   name=f'{member.display_name} • Sala'[:90]
   try:
    ch=await member.guild.create_voice_channel(name,category=category,reason=f'Nexus temp voice owner {member.id}')
    await self.pool.execute('INSERT INTO sistemas_temp_voice(channel_id,guild_id,owner_id) VALUES($1,$2,$3) ON CONFLICT(channel_id) DO NOTHING',ch.id,member.guild.id,member.id)
    await member.move_to(ch);await self.audit(member.guild,member.id,'Sala temporária criada',{'channel_id':ch.id,'owner_id':member.id},'log_server_channel_id')
   except discord.HTTPException:log.exception('Temp voice create failed')
  if before.channel and before.channel.id!= (trigger_id or -1):
   row=await self.pool.fetchrow('SELECT owner_id FROM sistemas_temp_voice WHERE channel_id=$1',before.channel.id)
   if row and not before.channel.members:
    try:await before.channel.delete(reason='Nexus temporary voice empty cleanup');await self.pool.execute('DELETE FROM sistemas_temp_voice WHERE channel_id=$1',before.channel.id)
    except discord.HTTPException:log.exception('Temp voice cleanup failed')
 @app_commands.command(name='temp_voice_config',description='Configurar canal gatilho e categoria para salas temporárias.')
 @app_commands.checks.has_permissions(administrator=True)
 async def temp_voice_config(self,inter,trigger:discord.VoiceChannel,category:Optional[discord.CategoryChannel]=None):
  await self.setcfg(inter.guild.id,'temp_voice_trigger_id',trigger.id);await self.setcfg(inter.guild.id,'temp_voice_category_id',category.id if category else trigger.category_id);await reply(inter,f'Canal gatilho {trigger.mention} configurado. Salas vazias são excluídas automaticamente.')
 @commands.Cog.listener()
 async def on_command_completion(self,ctx):
  if ctx.guild:await self.audit(ctx.guild,ctx.author.id,'Comando prefixo',{'command':ctx.command.qualified_name if ctx.command else '?','channel_id':ctx.channel.id},'log_internal_channel_id')
 @commands.Cog.listener()
 async def on_app_command_completion(self,inter,command):
  if inter.guild:await self.audit(inter.guild,inter.user.id,'Comando slash',{'command':command.qualified_name,'channel_id':inter.channel_id},'log_internal_channel_id')
 @commands.Cog.listener()
 async def on_app_command_error(self,inter,error):
  log.error('Application command failure',exc_info=error)
  try:await reply(inter,'Falha ao executar. Erro técnico registrado, sem expor dados sensíveis.')
  except Exception:pass
  if inter.guild:await self.audit(inter.guild,inter.user.id,'Erro de comando',{'command':getattr(inter.command,'name','?'),'error_type':type(error).__name__},'log_internal_channel_id',RED)

class NexusPublicPanel(discord.ui.View):
 def __init__(self):super().__init__(timeout=None)
 @discord.ui.button(label='Ajuda & Comandos',style=discord.ButtonStyle.primary,custom_id='nexus:public:help',emoji='📘')
 async def help(self,i,b):await reply(i,em=embed('NEXUS • AJUDA','Prefixo `.`, slash commands disponíveis. `.help` exibe comandos. Economia: `.wallet`, `.daily`, `.work`, `.pay ID valor`. Staff: `.mod`, `.logs`, `.quarentena ID motivo`, `.liberar ID motivo`.'))
 @discord.ui.button(label='Status',style=discord.ButtonStyle.secondary,custom_id='nexus:public:status',emoji='📡')
 async def status(self,i,b):
  cog=i.client.get_cog('Systems');await cog.status_cmd.callback(cog,i)
 @discord.ui.button(label='Denunciar',style=discord.ButtonStyle.danger,custom_id='nexus:public:report',emoji='🛡️')
 async def report(self,i,b):await i.response.send_modal(QuickReportModal())
 @discord.ui.button(label='Sugestão',style=discord.ButtonStyle.secondary,custom_id='nexus:public:suggest',emoji='💡')
 async def suggest(self,i,b):await i.response.send_modal(QuickSuggestionModal())
 @discord.ui.button(label='Apelação',style=discord.ButtonStyle.secondary,custom_id='nexus:public:appeal',emoji='📨')
 async def appeal(self,i,b):await i.response.send_modal(QuickAppealModal())
class QuickSuggestionModal(discord.ui.Modal,title='Nexus • Sugestão'):
 content=discord.ui.TextInput(label='Sua sugestão',style=discord.TextStyle.paragraph,min_length=10,max_length=1800)
 async def on_submit(self,i):await i.client.get_cog('Systems').suggest_slash.callback(i.client.get_cog('Systems'),i,self.content.value)
class QuickAppealModal(discord.ui.Modal,title='Nexus • Apelação'):
 case_id=discord.ui.TextInput(label='Número do caso',min_length=1,max_length=12)
 explanation=discord.ui.TextInput(label='Explique por que pede revisão',style=discord.TextStyle.paragraph,min_length=10,max_length=1500)
 evidence=discord.ui.TextInput(label='URL de prova (opcional)',required=False,max_length=500)
 async def on_submit(self,i):
  if not self.case_id.value.isdigit():return await reply(i,'Número de caso inválido.')
  await i.client.get_cog('Systems').appeal_slash.callback(i.client.get_cog('Systems'),i,int(self.case_id.value),self.explanation.value,self.evidence.value or '')
class QuickReportModal(discord.ui.Modal,title='Nexus • Denúncia'):
 target=discord.ui.TextInput(label='ID do membro',min_length=17,max_length=20);reason=discord.ui.TextInput(label='Relato',style=discord.TextStyle.paragraph,min_length=10,max_length=1500);evidence=discord.ui.TextInput(label='Provas (URL opcional)',required=False,max_length=500)
 async def on_submit(self,i):
  cog=i.client.get_cog('Systems')
  if not self.target.value.isdigit():return await reply(i,'ID inválido.')
  await cog.report_slash.callback(cog,i,await i.client.fetch_user(int(self.target.value)),self.reason.value,self.evidence.value or None)
class NexusRemotePanel(discord.ui.View):
 def __init__(self):super().__init__(timeout=180)
 async def check(self,i):
  ids=set(int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS','').split(',') if x.strip().isdigit())
  if i.user.id not in ids:await reply(i,'Acesso remoto negado.');return False
  return True
 @discord.ui.button(label='Listar servidores',style=discord.ButtonStyle.primary,custom_id='nexus:remote:guilds')
 async def guilds(self,i,b):
  if not await self.check(i):return
  rows=[f'**{g.name}** • `{g.id}` • {g.member_count or "?"} membros' for g in i.client.guilds];await reply(i,em=embed('NEXUS • SERVIDORES', '\n'.join(rows[:40]) or 'Nenhum servidor.'))
 @discord.ui.button(label='Enviar mensagem',style=discord.ButtonStyle.secondary,custom_id='nexus:remote:send')
 async def send(self,i,b):
  if not await self.check(i):return
  await i.response.send_modal(RemoteMessageModal())
 @discord.ui.button(label='Monitoramento',style=discord.ButtonStyle.success,custom_id='nexus:remote:monitor')
 async def monitor(self,i,b):
  if not await self.check(i):return
  cog=i.client.get_cog('Systems');await cog.status_cmd.callback(cog,i)
class RemoteMessageModal(discord.ui.Modal,title='Remote Ops • Envio controlado'):
 guild_id=discord.ui.TextInput(label='ID do servidor',min_length=17,max_length=20);channel_id=discord.ui.TextInput(label='ID do canal',min_length=17,max_length=20);content=discord.ui.TextInput(label='Mensagem',style=discord.TextStyle.paragraph,max_length=1900)
 async def on_submit(self,i):
  ids=set(int(x) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS','').split(',') if x.strip())
  if i.user.id not in ids:return await reply(i,'Acesso remoto negado.')
  if not self.guild_id.value.isdigit() or not self.channel_id.value.isdigit():return await reply(i,'IDs inválidos.')
  g=i.client.get_guild(int(self.guild_id.value));ch=g.get_channel(int(self.channel_id.value)) if g else None
  if not isinstance(ch,(discord.TextChannel,discord.Thread)):return await reply(i,'Canal não encontrado ou tipo não permitido.')
  try:await ch.send(self.content.value,allowed_mentions=discord.AllowedMentions.none())
  except discord.HTTPException as e:return await reply(i,f'Falha de envio: {clip(e,200)}')
  cog=i.client.get_cog('Systems');await cog.audit(g,i.user.id,'Remote Ops • mensagem enviada',{'channel_id':ch.id,'content_length':len(self.content.value)},'log_internal_channel_id');await reply(i,'Mensagem enviada e auditada.')
class RequestDecisionView(discord.ui.View):
 def __init__(self,rid):super().__init__(timeout=None);self.rid=rid
 async def interaction_check(self,i):
  cog=i.client.get_cog('Systems');cfg=await cog.config(i.guild.id)
  if not staff(i.user,cfg):await reply(i,'Somente staff configurada.');return False
  return True
 @discord.ui.button(label='Aprovar',style=discord.ButtonStyle.success,custom_id='nexus:req:approve')
 async def approve(self,i,b):await i.client.get_cog('Systems').decision(i,self.rid,'approved')
 @discord.ui.button(label='Recusar',style=discord.ButtonStyle.danger,custom_id='nexus:req:deny')
 async def deny(self,i,b):await i.client.get_cog('Systems').decision(i,self.rid,'denied')
class AppealDecisionView(discord.ui.View):
 def __init__(self,aid):super().__init__(timeout=None);self.aid=aid
 async def interaction_check(self,i):
  cfg=await i.client.get_cog('Systems').config(i.guild.id)
  if not staff(i.user,cfg):await reply(i,'Somente staff.');return False
  return True
 @discord.ui.button(label='Aceitar',style=discord.ButtonStyle.success,custom_id='nexus:appeal:approve')
 async def accept(self,i,b):await i.client.get_cog('Systems').appeal_decision(i,self.aid,'approved','Recurso aceito')
 @discord.ui.button(label='Recusar',style=discord.ButtonStyle.danger,custom_id='nexus:appeal:deny')
 async def reject(self,i,b):await i.client.get_cog('Systems').appeal_decision(i,self.aid,'denied','Recurso recusado')

async def setup(bot):
 main=sys.modules.get('__main__') or sys.modules.get('main');pool=getattr(main,'db_pool',None) if main else None
 if pool is None or not hasattr(pool,'acquire'):raise RuntimeError('Pool asyncpg db_pool do main.py não foi localizado antes do load de sistemas.')
 current=bot.command_prefix
 if isinstance(current,str):bot.command_prefix=commands.when_mentioned_or('.',current)
 elif isinstance(current,(tuple,list)):bot.command_prefix=commands.when_mentioned_or('.',*current)
 elif callable(current):
  old=current
  async def prefixmix(b,m):
   got=old(b,m);got=await got if hasattr(got,'__await__') else got;return list(dict.fromkeys(['.',*([got] if isinstance(got,str) else got or [])]))
  bot.command_prefix=prefixmix
 await bot.add_cog(Systems(bot,pool))
 # Add-on extension is independent and loaded exactly once; main.py remains unchanged.
 if 'comandosextra' not in bot.extensions:
  try: await bot.load_extension('comandosextra')
  except Exception: log.exception('comandosextra extension failed; core Nexus remains loaded')
