# -*- coding: utf-8 -*-
"""Nexus optional command pack. Independently loadable discord.py extension."""
from __future__ import annotations
import logging, os, random, re
from datetime import datetime, timezone, timedelta
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands, tasks
log=logging.getLogger('nexus.extra')
PURPLE=discord.Colour(0x7C3AED)
def em(title,desc='',color=PURPLE):
 e=discord.Embed(title=title,description=desc,color=color,timestamp=datetime.now(timezone.utc));e.set_footer(text='NEXUS • Módulo Extra');return e
async def ep(i,text=None,embed=None):
 if i.response.is_done():await i.followup.send(content=text,embed=embed,ephemeral=True)
 else:await i.response.send_message(content=text,embed=embed,ephemeral=True)
def env_admins():return {int(x.strip()) for x in os.getenv('NEXUS_REMOTE_ADMIN_IDS','').split(',') if x.strip().isdigit()}
class StaffTaskView(discord.ui.View):
 def __init__(self,taskid):super().__init__(timeout=None);self.taskid=taskid
 @discord.ui.button(label='Concluir tarefa',style=discord.ButtonStyle.success,custom_id='nexus:task:done')
 async def done(self,i,b):
  cog=i.client.get_cog('NexusExtra');row=await cog.pool.fetchrow('SELECT * FROM nexus_staff_tasks WHERE id=$1 AND guild_id=$2',self.taskid,i.guild.id)
  if not row:return await ep(i,'Tarefa inexistente.')
  if i.user.id not in (row['assignee_id'],row['creator_id']) and not i.user.guild_permissions.manage_guild:return await ep(i,'Somente responsável, criador ou administrador pode concluir.')
  await cog.pool.execute("UPDATE nexus_staff_tasks SET status='completed' WHERE id=$1",self.taskid);await ep(i,'Tarefa marcada como concluída.')
class NexusExtra(commands.Cog):
 def __init__(self,bot):self.bot=bot;self.core=bot.get_cog('Systems');self.pool=self.core.pool;self.event_loop.start()
 async def cog_load(self):
  await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_staff_tasks(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,assignee_id BIGINT NOT NULL,creator_id BIGINT NOT NULL,title TEXT NOT NULL,details TEXT,due_at TIMESTAMPTZ,status TEXT DEFAULT 'open',created_at TIMESTAMPTZ DEFAULT NOW())")
  await self.pool.execute('ALTER TABLE nexus_staff_tasks ADD COLUMN IF NOT EXISTS message_id BIGINT')
  await self.pool.execute('ALTER TABLE nexus_events ADD COLUMN IF NOT EXISTS message_id BIGINT')
  await self.pool.execute('ALTER TABLE nexus_events ADD COLUMN IF NOT EXISTS winner_count INTEGER NOT NULL DEFAULT 1')
  await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_virtual_items(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,name TEXT NOT NULL,description TEXT,price BIGINT NOT NULL,stock INTEGER DEFAULT -1,active BOOLEAN DEFAULT TRUE)")
  await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_inventory(guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,item_id BIGINT NOT NULL,quantity INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guild_id,user_id,item_id))")
  await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_staff_applications(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,user_id BIGINT NOT NULL,answers JSONB NOT NULL,status TEXT DEFAULT 'pending',reviewer_id BIGINT,decision_reason TEXT,created_at TIMESTAMPTZ DEFAULT NOW(),decided_at TIMESTAMPTZ)")
  task_rows=await self.pool.fetch('SELECT id,message_id FROM nexus_staff_tasks WHERE status=\'open\' AND message_id IS NOT NULL')
  for r in task_rows:self.bot.add_view(StaffTaskView(int(r['id'])),message_id=r['message_id'])
  rows=await self.pool.fetch("SELECT id,message_id FROM nexus_events WHERE status='open' AND message_id IS NOT NULL")
  for r in rows:self.bot.add_view(EventJoinView(int(r['id'])),message_id=r['message_id'])
  self.bot.add_view(RecruitmentView())
 def cog_unload(self):self.event_loop.cancel()
 async def require_staff(self,i):
  cfg=await self.core.config(i.guild.id)
  from sistemas import staff
  if not staff(i.user,cfg):await ep(i,'Comando reservado à equipe configurada.');return False
  return True
 @app_commands.command(name='staff_tarefa',description='Criar e atribuir tarefa à equipe.')
 async def task_create(self,i,assignee:discord.Member,title:str,details:str,due:str=''):
  if not await self.require_staff(i):return
  due_at=None
  if due:
   try:due_at=datetime.strptime(due,'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
   except ValueError:return await ep(i,'Prazo inválido. Formato UTC: YYYY-MM-DD HH:MM.')
  tid=await self.pool.fetchval('INSERT INTO nexus_staff_tasks(guild_id,assignee_id,creator_id,title,details,due_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',i.guild.id,assignee.id,i.user.id,title,details,due_at)
  e=em(f'NEXUS STAFF • Tarefa #{tid}',f'**{title}**\n{details}');e.add_field(name='Responsável',value=assignee.mention);e.add_field(name='Criador',value=i.user.mention);e.add_field(name='Prazo UTC',value=due_at.strftime('%Y-%m-%d %H:%M') if due_at else 'Sem prazo')
  try:dm=await assignee.send(embed=e,view=StaffTaskView(tid));await self.pool.execute('UPDATE nexus_staff_tasks SET message_id=$2 WHERE id=$1',tid,dm.id)
  except discord.HTTPException:pass
  await ep(i,f'Tarefa #{tid} criada e atribuída.')
 @app_commands.command(name='staff_tarefas',description='Consultar tarefas da equipe.')
 async def task_list(self,i,status:str='open'):
  if not await self.require_staff(i):return
  if status not in ('open','completed','all'):return await ep(i,'Status permitido: open, completed ou all.')
  q="SELECT id,assignee_id,title,status,due_at FROM nexus_staff_tasks WHERE guild_id=$1";args=[i.guild.id]
  if status!='all':q+=' AND status=$2';args.append(status)
  rows=await self.pool.fetch(q+' ORDER BY id DESC LIMIT 20',*args);e=em('NEXUS STAFF • TAREFAS',f'{len(rows)} tarefa(s)')
  for r in rows:e.add_field(name=f'#{r["id"]} • {r["title"]}',value=f'Responsável <@{r["assignee_id"]}> • {r["status"]}\nPrazo: {r["due_at"] or "—"}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='staff_registrar',description='Cadastrar/ativar integrante staff.')
 async def staff_register(self,i,member:discord.Member,role_title:str):
  if not await self.require_staff(i):return
  await self.pool.execute('INSERT INTO sistemas_staff(guild_id,user_id,active,role_name,last_seen) VALUES($1,$2,TRUE,$3,NOW()) ON CONFLICT(guild_id,user_id) DO UPDATE SET active=TRUE,role_name=EXCLUDED.role_name,last_seen=NOW()',i.guild.id,member.id,role_title)
  await self.core.audit(i.guild,i.user.id,'Staff registrado',{'member_id':member.id,'staff_title':role_title});await ep(i,f'{member.mention} registrado como {role_title}.')
 @app_commands.command(name='staff_lista',description='Listar staff registrada e situação.')
 async def staff_list(self,i):
  if not await self.require_staff(i):return
  rows=await self.pool.fetch('SELECT user_id,active,role_name,last_seen FROM sistemas_staff WHERE guild_id=$1 ORDER BY active DESC,last_seen DESC LIMIT 50',i.guild.id);e=em('NEXUS STAFF • REGISTRO',f'{len(rows)} membro(s)')
  for r in rows:e.add_field(name=f'<@{r["user_id"]}> • {r["role_name"] or "Staff"}',value=f'{"Ativo" if r["active"] else "Inativo"} • Atualizado: {r["last_seen"]}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='loja_produto',description='Cadastrar produto na loja Nexus (não é economia virtual).')
 async def product_create(self,i,name:str,price_brl:float,stock:int,description:str,category:str='Geral'):
  if not await self.require_staff(i):return
  if price_brl<=0 or stock<0:return await ep(i,'Preço deve ser positivo e estoque não negativo.')
  cents=round(price_brl*100);pid=await self.pool.fetchval('INSERT INTO nexus_products(guild_id,name,description,price_cents,stock,category) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',i.guild.id,name,description,cents,stock,category)
  await self.core.audit(i.guild,i.user.id,'Produto criado',{'product_id':pid,'name':name,'price_cents':cents,'stock':stock},'log_internal_channel_id');await ep(i,f'Produto cadastrado #{pid}. Pagamento externo não está ativado sem provedor/credenciais.')
 @app_commands.command(name='loja_estoque',description='Ajustar estoque ou disponibilidade do produto.')
 async def product_stock(self,i,product_id:int,stock:int,active:bool=True):
  if not await self.require_staff(i):return
  if stock<0:return await ep(i,'Estoque não pode ser negativo.')
  res=await self.pool.execute('UPDATE nexus_products SET stock=$3,active=$4 WHERE id=$1 AND guild_id=$2',product_id,i.guild.id,stock,active)
  if res.endswith('0'):return await ep(i,'Produto não encontrado neste servidor.')
  await self.core.audit(i.guild,i.user.id,'Estoque de produto alterado',{'product_id':product_id,'stock':stock,'active':active});await ep(i,'Estoque/estado atualizado.')
 @app_commands.command(name='loja_catalogo',description='Exibir catálogo Nexus do servidor.')
 async def product_catalog(self,i):
  rows=await self.pool.fetch('SELECT id,name,description,price_cents,stock,category FROM nexus_products WHERE guild_id=$1 AND active=TRUE ORDER BY category,id LIMIT 25',i.guild.id);e=em('NEXUS • LOJA',f'{len(rows)} produtos ativos\nPagamentos reais não habilitados nesta versão: pedidos ficam pendentes, sem falsa confirmação.')
  for r in rows:e.add_field(name=f'#{r["id"]} • {r["name"]} • R$ {r["price_cents"]/100:.2f}',value=f'{r["description"][:250]}\nCategoria: {r["category"]} • Estoque: {r["stock"]}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='loja_pedido',description='Criar pedido (não marca como pago sem confirmação externa).')
 async def order_create(self,i,product_id:int,quantity:app_commands.Range[int,1,10]=1):
  row=await self.pool.fetchrow('SELECT * FROM nexus_products WHERE id=$1 AND guild_id=$2 AND active=TRUE FOR UPDATE',product_id,i.guild.id)
  if not row:return await ep(i,'Produto não encontrado/indisponível.')
  if row['stock']<quantity:return await ep(i,'Estoque insuficiente.')
  total=row['price_cents']*quantity
  async with self.pool.acquire() as c:
   async with c.transaction():
    updated=await c.fetchval('UPDATE nexus_products SET stock=stock-$2 WHERE id=$1 AND stock>=$2 RETURNING id',product_id,quantity)
    if not updated:return await ep(i,'Estoque mudou; tente novamente.')
    oid=await c.fetchval('INSERT INTO nexus_orders(guild_id,user_id,product_id,qty,status,total_cents) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',i.guild.id,i.user.id,product_id,quantity,'pending',total)
  await self.core.audit(i.guild,i.user.id,'Pedido da loja criado',{'order_id':oid,'product_id':product_id,'quantity':quantity,'total_cents':total});await ep(i,f'Pedido **#{oid}** criado, total R$ {total/100:.2f}. Status: **PENDENTE**. Não há pagamento confirmado; aguarde contato da equipe.')
 @app_commands.command(name='loja_pedidos',description='Consultar pedidos da loja.')
 async def order_list(self,i,status:str='all'):
  if not await self.require_staff(i):return
  if status not in ('all','pending','paid','delivered','cancelled'):return await ep(i,'Status inválido.')
  q='SELECT id,user_id,product_id,qty,status,total_cents,created_at FROM nexus_orders WHERE guild_id=$1';args=[i.guild.id]
  if status!='all':q+=' AND status=$2';args.append(status)
  rows=await self.pool.fetch(q+' ORDER BY id DESC LIMIT 20',*args);e=em('NEXUS • PEDIDOS',f'{len(rows)} pedido(s)')
  for r in rows:e.add_field(name=f'Pedido #{r["id"]} • {r["status"]}',value=f'Cliente <@{r["user_id"]}> • Produto #{r["product_id"]} • Qtde {r["qty"]}\nTotal R$ {r["total_cents"]/100:.2f}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='loja_status_pedido',description='Atualizar status de pedido (paid só por confirmação real do provedor).')
 async def order_status(self,i,order_id:int,status:str):
  if not await self.require_staff(i):return
  if status not in ('delivered','cancelled'):return await ep(i,'A equipe só pode definir entregue/cancelado manualmente. O estado paid exige webhook/provedor real.')
  row=await self.pool.fetchrow('SELECT * FROM nexus_orders WHERE id=$1 AND guild_id=$2',order_id,i.guild.id)
  if not row:return await ep(i,'Pedido não encontrado.')
  if row['status'] in ('paid','delivered'):return await ep(i,'Pedido pago/entregue não pode ser cancelado aqui.')
  await self.pool.execute('UPDATE nexus_orders SET status=$2 WHERE id=$1',order_id,status)
  if status=='cancelled':await self.pool.execute('UPDATE nexus_products SET stock=stock+$2 WHERE id=$1',row['product_id'],row['qty'])
  await self.core.audit(i.guild,i.user.id,'Pedido atualizado',{'order_id':order_id,'status':status});await ep(i,'Pedido atualizado e registrado.')
 @app_commands.command(name='evento_criar',description='Criar evento comunitário com inscrições persistentes.')
 async def event_create(self,i,title:str,description:str,duration_hours:app_commands.Range[int,1,720]=24):
  if not i.user.guild_permissions.manage_events and not await self.require_staff(i):return
  end=datetime.now(timezone.utc)+timedelta(hours=duration_hours);eid=await self.pool.fetchval('INSERT INTO nexus_events(guild_id,creator_id,title,description,channel_id,ends_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',i.guild.id,i.user.id,title,description,i.channel_id,end)
  msg=await i.channel.send(embed=em(f'NEXUS • EVENTO #{eid}',f'**{title}**\n{description}\n\nInscrições terminam <t:{int(end.timestamp())}:R>'),view=EventJoinView(eid));await self.pool.execute('UPDATE nexus_events SET message_id=$2 WHERE id=$1',eid,msg.id);await ep(i,f'Evento #{eid} publicado. Mensagem {msg.id}.')
 @app_commands.command(name='sorteio_criar',description='Criar sorteio com participantes persistentes.')
 async def raffle_create(self,i,title:str,description:str,winner_count:app_commands.Range[int,1,10]=1,duration_hours:app_commands.Range[int,1,720]=24):
  if not i.user.guild_permissions.manage_events and not await self.require_staff(i):return
  end=datetime.now(timezone.utc)+timedelta(hours=duration_hours);eid=await self.pool.fetchval('INSERT INTO nexus_events(guild_id,creator_id,title,description,channel_id,ends_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',i.guild.id,i.user.id,'SORTEIO: '+title,description,i.channel_id,end)
  msg=await i.channel.send(embed=em(f'🎉 SORTEIO #{eid}',f'**{title}**\n{description}\nVencedores: {winner_count}\nTermina <t:{int(end.timestamp())}:R>'),view=EventJoinView(eid));await self.pool.execute('UPDATE nexus_events SET message_id=$2,winner_count=$3 WHERE id=$1',eid,msg.id,winner_count);await ep(i,f'Sorteio #{eid} criado.')
 @app_commands.command(name='evento_encerrar',description='Encerrar evento/sorteio e sortear vencedores.')
 async def event_close(self,i,event_id:int):
  if not await self.require_staff(i):return
  row=await self.pool.fetchrow('SELECT * FROM nexus_events WHERE id=$1 AND guild_id=$2 AND status=\'open\'',event_id,i.guild.id)
  if not row:return await ep(i,'Evento inexistente/encerrado.')
  entries=await self.pool.fetch('SELECT user_id FROM nexus_raffle_entries WHERE event_id=$1',event_id);ids=[r['user_id'] for r in entries]
  wcount=int(row['winner_count'] or 1);winners=random.sample(ids,min(wcount,len(ids))) if ids else []
  await self.pool.execute('UPDATE nexus_events SET status=\'closed\' WHERE id=$1',event_id)
  ch=i.guild.get_channel(row['channel_id'])
  if ch:await ch.send(embed=em(f'NEXUS • EVENTO #{event_id} ENCERRADO',f'Participantes: {len(ids)}\nVencedor(es): '+(', '.join(f'<@{x}>' for x in winners) if winners else 'Sem participantes.')))
  await ep(i,'Evento encerrado. Sorteio registrado.')
 @app_commands.command(name='economia_daily',description='Receber recompensa diária da economia virtual.')
 async def economy_daily(self,i):
  await self.core.daily(i.guild,i.user);await ep(i,'Verifique sua DM para a recompensa diária. O cooldown é persistido no banco.')
 @app_commands.command(name='economia_work',description='Trabalhar e ganhar moedas virtuais respeitando cooldown.')
 async def economy_work(self,i):
  await self.core.work(i.guild,i.user);await ep(i,'Verifique sua DM. Se o cooldown estiver ativo, a resposta informa o tempo de espera.')
 @app_commands.command(name='economia_carteira',description='Consultar sua carteira de economia virtual.')
 async def economy_wallet(self,i,member:Optional[discord.Member]=None):
  target=member or i.user
  if member and member.id!=i.user.id and not await self.require_staff(i):return
  await self.core.ensure_wallet(i.guild.id,target.id);bal=await self.pool.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2',i.guild.id,target.id) or 0;await ep(i,embed=em('NEXUS • WALLET',f'{target.mention} tem **{bal:,} NXC**. Moeda virtual sem valor monetário real.'))
 @app_commands.command(name='economia_transferir',description='Transferir moedas virtuais a um membro.')
 async def economy_transfer(self,i,target:discord.Member,amount:app_commands.Range[int,1,100000000]):
  if target.id==i.user.id:return await ep(i,'Não transfira para si mesmo.')
  await self.core.ensure_wallet(i.guild.id,i.user.id);await self.core.ensure_wallet(i.guild.id,target.id)
  async with self.pool.acquire() as c:
   async with c.transaction():
    await c.execute('SELECT pg_advisory_xact_lock($1)',i.user.id)
    bal=await c.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE',i.guild.id,i.user.id)
    if bal<amount:return await ep(i,'Saldo insuficiente.')
    await c.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2',i.guild.id,i.user.id,amount);await c.execute('UPDATE nexus_wallets SET balance=balance+$3 WHERE guild_id=$1 AND user_id=$2',i.guild.id,target.id,amount);await c.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$3,$4,$5)',i.guild.id,i.user.id,target.id,amount,'transfer')
  await self.core.audit(i.guild,i.user.id,'Transferência economia',{'target_id':target.id,'amount':amount});await ep(i,'Transferência realizada.')
 @app_commands.command(name='economia_item_criar',description='Cadastrar item para loja virtual de moedas.')
 async def virtual_item_create(self,i,name:str,description:str,price:app_commands.Range[int,1,1000000],stock:int=-1):
  if not await self.require_staff(i):return
  if stock < -1:return await ep(i,'Estoque deve ser -1 (ilimitado) ou positivo.')
  item=await self.pool.fetchval('INSERT INTO nexus_virtual_items(guild_id,name,description,price,stock) VALUES($1,$2,$3,$4,$5) RETURNING id',i.guild.id,name,description,price,stock);await ep(i,f'Item virtual #{item} criado.')
 @app_commands.command(name='economia_itens',description='Ver catálogo da economia virtual.')
 async def virtual_item_list(self,i):
  rows=await self.pool.fetch('SELECT id,name,description,price,stock FROM nexus_virtual_items WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 25',i.guild.id);e=em('NEXUS • LOJA VIRTUAL',f'{len(rows)} itens. Compras usam NXC; não são pagamentos reais.')
  for r in rows:e.add_field(name=f'#{r["id"]} • {r["name"]} • {r["price"]} NXC',value=f'{r["description"] or "—"}\nEstoque: {"ilimitado" if r["stock"]<0 else r["stock"]}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='economia_comprar',description='Comprar item da loja virtual usando NXC.')
 async def virtual_item_buy(self,i,item_id:int,quantity:app_commands.Range[int,1,20]=1):
  await self.core.ensure_wallet(i.guild.id,i.user.id)
  async with self.pool.acquire() as c:
   async with c.transaction():
    item=await c.fetchrow('SELECT * FROM nexus_virtual_items WHERE id=$1 AND guild_id=$2 AND active=TRUE FOR UPDATE',item_id,i.guild.id)
    if not item:return await ep(i,'Item não encontrado ou inativo.')
    if item['stock']>=0 and item['stock']<quantity:return await ep(i,'Estoque insuficiente.')
    total=item['price']*quantity;bal=await c.fetchval('SELECT balance FROM nexus_wallets WHERE guild_id=$1 AND user_id=$2 FOR UPDATE',i.guild.id,i.user.id)
    if bal<total:return await ep(i,'Saldo NXC insuficiente.')
    await c.execute('UPDATE nexus_wallets SET balance=balance-$3 WHERE guild_id=$1 AND user_id=$2',i.guild.id,i.user.id,total)
    if item['stock']>=0:await c.execute('UPDATE nexus_virtual_items SET stock=stock-$2 WHERE id=$1',item_id,quantity)
    await c.execute('INSERT INTO nexus_inventory(guild_id,user_id,item_id,quantity) VALUES($1,$2,$3,$4) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=nexus_inventory.quantity+EXCLUDED.quantity',i.guild.id,i.user.id,item_id,quantity)
    await c.execute('INSERT INTO nexus_economy_tx(guild_id,from_user,to_user,amount,kind) VALUES($1,$2,$2,$3,$4)',i.guild.id,i.user.id,total,'virtual_shop_purchase')
  await ep(i,f'Compra concluída: {quantity} × **{item["name"]}** por {total} NXC. Item registrado no inventário.')
 @app_commands.command(name='economia_inventario',description='Consultar inventário da economia virtual.')
 async def virtual_inventory(self,i):
  rows=await self.pool.fetch('SELECT v.name,v.description,n.quantity FROM nexus_inventory n JOIN nexus_virtual_items v ON v.id=n.item_id WHERE n.guild_id=$1 AND n.user_id=$2 ORDER BY v.name',i.guild.id,i.user.id);e=em('NEXUS • INVENTÁRIO',f'{len(rows)} item(ns)')
  for r in rows:e.add_field(name=f'{r["name"]} × {r["quantity"]}',value=r['description'] or '—',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='staff_recrutamento_config',description='Definir canal de recrutamento staff.')
 @app_commands.checks.has_permissions(administrator=True)
 async def recruitment_config(self,i,channel:discord.TextChannel):
  await self.core.setcfg(i.guild.id,'recruitment_channel_id',channel.id);await ep(i,f'Canal de recrutamento: {channel.mention}')
 @app_commands.command(name='staff_recrutamento_publicar',description='Publicar painel de candidatura staff.')
 @app_commands.checks.has_permissions(administrator=True)
 async def recruitment_publish(self,i,channel:Optional[discord.TextChannel]=None):
  cfg=await self.core.config(i.guild.id);target=channel or i.guild.get_channel(cfg.get('recruitment_channel_id'))
  if not target:return await ep(i,'Configure o canal com /staff_recrutamento_config.')
  await target.send(embed=em('NEXUS STAFF • RECRUTAMENTO','A equipe está recebendo candidaturas. Responda ao formulário com informações verdadeiras e detalhadas.'),view=RecruitmentView());await ep(i,f'Painel publicado em {target.mention}.')
 @app_commands.command(name='staff_candidaturas',description='Listar candidaturas pendentes.')
 async def applications(self,i,status:str='pending'):
  if not await self.require_staff(i):return
  if status not in ('pending','approved','denied','all'):return await ep(i,'Status inválido.')
  q='SELECT id,user_id,answers,status,created_at FROM nexus_staff_applications WHERE guild_id=$1';args=[i.guild.id]
  if status!='all':q+=' AND status=$2';args.append(status)
  rows=await self.pool.fetch(q+' ORDER BY id DESC LIMIT 15',*args);e=em('NEXUS STAFF • CANDIDATURAS',f'{len(rows)} candidaturas')
  for r in rows:e.add_field(name=f'#{r["id"]} • <@{r["user_id"]}> • {r["status"]}',value=str(r['answers'])[:700],inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='staff_decidir_candidatura',description='Aprovar ou recusar candidatura staff.')
 async def application_decide(self,i,application_id:int,decision:str,reason:str):
  if not await self.require_staff(i):return
  if decision not in ('approved','denied'):return await ep(i,'Decisão deve ser approved ou denied.')
  row=await self.pool.fetchrow("SELECT * FROM nexus_staff_applications WHERE id=$1 AND guild_id=$2 AND status='pending'",application_id,i.guild.id)
  if not row:return await ep(i,'Candidatura não encontrada ou já decidida.')
  await self.pool.execute('UPDATE nexus_staff_applications SET status=$2,reviewer_id=$3,decision_reason=$4,decided_at=NOW() WHERE id=$1',application_id,decision,i.user.id,reason)
  try:u=await self.bot.fetch_user(row['user_id']);await u.send(embed=em('NEXUS STAFF • Resultado',f'Candidatura #{application_id}: **{decision}**\nJustificativa: {reason}'))
  except discord.HTTPException:pass
  await self.core.audit(i.guild,i.user.id,'Candidatura staff decidida',{'application_id':application_id,'decision':decision,'reason':reason});await ep(i,'Decisão registrada e notificação tentada.')
 @app_commands.command(name='staff_reuniao',description='Agendar/avisar reunião de equipe no canal selecionado.')
 async def staff_meeting(self,i,channel:discord.TextChannel,title:str,when_utc:str,details:str):
  if not await self.require_staff(i):return
  try:when=datetime.strptime(when_utc,'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
  except ValueError:return await ep(i,'Formato horário UTC inválido: YYYY-MM-DD HH:MM.')
  e=em('NEXUS STAFF • REUNIÃO',f'**{title}**\n{details}\n\nHorário: <t:{int(when.timestamp())}:F> (<t:{int(when.timestamp())}:R>)');await channel.send(embed=e);await self.core.audit(i.guild,i.user.id,'Aviso de reunião staff',{'channel_id':channel.id,'title':title,'meeting_time_utc':when.isoformat()});await ep(i,'Aviso publicado e auditado.')
 @app_commands.command(name='anuncio_agendar',description='Agendar anúncio. Mensagem será publicada pelo bot no horário UTC.')
 async def announcement_schedule(self,i,channel:discord.TextChannel,content:str,when_utc:str):
  if not await self.require_staff(i):return
  try:when=datetime.strptime(when_utc,'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
  except ValueError:return await ep(i,'Formato horário UTC inválido: YYYY-MM-DD HH:MM.')
  if when<=datetime.now(timezone.utc):return await ep(i,'O horário deve ser futuro.')
  aid=await self.pool.fetchval('INSERT INTO nexus_announcements(guild_id,channel_id,content,send_at,created_by) VALUES($1,$2,$3,$4,$5) RETURNING id',i.guild.id,channel.id,content,when,i.user.id);await self.core.audit(i.guild,i.user.id,'Anúncio agendado',{'announcement_id':aid,'channel_id':channel.id,'send_at':when.isoformat()});await ep(i,f'Anúncio #{aid} agendado.')
 @app_commands.command(name='webhook_criar',description='Criar webhook autorizado em canal de texto.')
 async def webhook_create(self,i,channel:discord.TextChannel,name:str):
  if not await self.require_staff(i):return
  if not channel.permissions_for(i.guild.me).manage_webhooks:return await ep(i,'Bot sem permissão Manage Webhooks no canal.')
  try:wh=await channel.create_webhook(name=name,reason=f'Nexus webhook setup by {i.user.id}')
  except discord.HTTPException as e:return await ep(i,f'Falha ao criar webhook: {clip(e,200)}')
  await self.core.audit(i.guild,i.user.id,'Webhook criado',{'channel_id':channel.id,'webhook_id':wh.id,'webhook_token_logged':False});await ep(i,f'Webhook criado. URL entregue em DM; guarde-a com segurança e não publique. ID `{wh.id}`.')
  try:await i.user.send(f'Webhook Nexus criado para {channel.mention}. URL (segredo): {wh.url}')
  except discord.HTTPException:await ep(i,'DM bloqueada; webhook criado mas URL não foi entregue. Você pode abrir configurações do canal e gerenciar o webhook.')
 @app_commands.command(name='webhook_listar',description='Listar IDs/nome dos webhooks no servidor sem revelar tokens.')
 async def webhook_list(self,i,channel:Optional[discord.TextChannel]=None):
  if not await self.require_staff(i):return
  if not i.guild.me.guild_permissions.manage_webhooks:return await ep(i,'Permissão Manage Webhooks necessária.')
  try:hooks=await (channel.webhooks() if channel else i.guild.webhooks())
  except discord.HTTPException as e:return await ep(i,f'Falha: {clip(e,200)}')
  e=em('NEXUS • WEBHOOKS',f'{len(hooks)} webhook(s); tokens não são exibidos.')
  for w in hooks[:25]:e.add_field(name=f'{w.name} • `{w.id}`',value=f'Canal: <#{w.channel_id}> • Criado por: {w.user or "desconhecido"}',inline=False)
  await ep(i,embed=e)
 @app_commands.command(name='webhook_remover',description='Remover webhook específico por ID.')
 async def webhook_delete(self,i,webhook_id:str):
  if not await self.require_staff(i):return
  if not webhook_id.isdigit():return await ep(i,'ID inválido.')
  try:
   w=await self.bot.fetch_webhook(int(webhook_id));g=i.guild.get_channel(w.channel_id)
   if w.guild_id!=i.guild.id:return await ep(i,'Webhook não pertence a este servidor.')
   await w.delete(reason=f'Removed by Nexus staff {i.user.id}')
  except discord.HTTPException as e:return await ep(i,f'Falha: {clip(e,200)}')
  await self.core.audit(i.guild,i.user.id,'Webhook removido',{'webhook_id':webhook_id});await ep(i,'Webhook removido.')
 @app_commands.command(name='membro_info',description='Consultar informações do membro no servidor.')
 async def member_info(self,i,member:discord.Member):
  e=em('NEXUS • FICHA DE MEMBRO',f'{member.mention} (`{member.id}`)');e.set_thumbnail(url=member.display_avatar.url);e.add_field(name='Conta criada',value=f'<t:{int(member.created_at.timestamp())}:F>',inline=True);e.add_field(name='Entrou',value=f'<t:{int(member.joined_at.timestamp())}:F>' if member.joined_at else 'Indisponível',inline=True);e.add_field(name='Cargos',value=', '.join(r.mention for r in member.roles[1:])[:900] or 'Nenhum',inline=False);await ep(i,embed=e)
 @app_commands.command(name='cargo_adicionar',description='Adicionar cargo ao membro com validação de hierarquia.')
 async def role_add(self,i,member:discord.Member,role:discord.Role,reason:str='Ajuste de cargo autorizado'):
  if not i.user.guild_permissions.manage_roles:return await ep(i,'Permissão Manage Roles necessária.')
  if role>=i.user.top_role or role>=i.guild.me.top_role:return await ep(i,'Hierarquia de cargo impede essa alteração.')
  try:await member.add_roles(role,reason=reason)
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  await self.core.audit(i.guild,i.user.id,'Cargo adicionado',{'member_id':member.id,'role_id':role.id,'reason':reason},'log_role_channel_id');await ep(i,'Cargo atribuído.')
 @app_commands.command(name='cargo_remover',description='Remover cargo do membro.')
 async def role_remove(self,i,member:discord.Member,role:discord.Role,reason:str='Ajuste de cargo autorizado'):
  if not i.user.guild_permissions.manage_roles:return await ep(i,'Permissão Manage Roles necessária.')
  if role>=i.user.top_role or role>=i.guild.me.top_role:return await ep(i,'Hierarquia de cargo impede essa alteração.')
  try:await member.remove_roles(role,reason=reason)
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  await self.core.audit(i.guild,i.user.id,'Cargo removido',{'member_id':member.id,'role_id':role.id,'reason':reason},'log_role_channel_id');await ep(i,'Cargo removido.')
 @app_commands.command(name='canal_criar',description='Criar canal de texto na categoria selecionada.')
 async def channel_create(self,i,name:str,category:Optional[discord.CategoryChannel]=None):
  if not i.user.guild_permissions.manage_channels:return await ep(i,'Permissão Manage Channels necessária.')
  name=re.sub(r'[^a-z0-9-]','-',name.lower()).strip('-')[:90]
  if not name:return await ep(i,'Nome inválido.')
  try:ch=await i.guild.create_text_channel(name,category=category,reason=f'Nexus admin by {i.user.id}')
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  await self.core.audit(i.guild,i.user.id,'Canal criado via Nexus',{'channel_id':ch.id,'name':name},'log_server_channel_id');await ep(i,f'Canal criado {ch.mention}.')
 @app_commands.command(name='canal_lock',description='Bloquear envio de mensagens no canal.')
 async def channel_lock(self,i,channel:Optional[discord.TextChannel]=None,reason:str='Lock administrativo'):
  if not i.user.guild_permissions.manage_channels:return await ep(i,'Manage Channels necessário.')
  ch=channel or i.channel;ow=ch.overwrites_for(i.guild.default_role);ow.send_messages=False;ow.add_reactions=False
  try:await ch.set_permissions(i.guild.default_role,overwrite=ow,reason=reason)
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  await self.core.audit(i.guild,i.user.id,'Canal bloqueado',{'channel_id':ch.id,'reason':reason},'log_server_channel_id');await ep(i,f'{ch.mention} bloqueado.')
 @app_commands.command(name='canal_unlock',description='Desbloquear envio de mensagens no canal.')
 async def channel_unlock(self,i,channel:Optional[discord.TextChannel]=None,reason:str='Unlock administrativo'):
  if not i.user.guild_permissions.manage_channels:return await ep(i,'Manage Channels necessário.')
  ch=channel or i.channel;ow=ch.overwrites_for(i.guild.default_role);ow.send_messages=None;ow.add_reactions=None
  try:await ch.set_permissions(i.guild.default_role,overwrite=ow,reason=reason)
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  await self.core.audit(i.guild,i.user.id,'Canal desbloqueado',{'channel_id':ch.id,'reason':reason},'log_server_channel_id');await ep(i,f'{ch.mention} desbloqueado.')
 @app_commands.command(name='sugestao_decidir',description='Registrar decisão sobre sugestão por protocolo.')
 async def suggestion_decide(self,i,suggestion_id:int,decision:str,reason:str=''):
  if not await self.require_staff(i):return
  if decision not in ('approved','denied','considering'):return await ep(i,'Decisão inválida: approved, denied ou considering.')
  r=await self.pool.fetchrow('SELECT * FROM sistemas_suggestions WHERE id=$1 AND guild_id=$2',suggestion_id,i.guild.id)
  if not r:return await ep(i,'Sugestão não encontrada.')
  await self.pool.execute('UPDATE sistemas_suggestions SET status=$3 WHERE id=$1 AND guild_id=$2',suggestion_id,i.guild.id,decision)
  if r['message_id']:
   ch=i.guild.get_channel((await self.core.config(i.guild.id)).get('suggestion_channel_id') or 0)
   try:m=await ch.fetch_message(r['message_id']);e=m.embeds[0] if m.embeds else em('Sugestão');e.add_field(name='Decisão',value=f'{decision} • {reason or "—"}');await m.edit(embed=e)
   except discord.HTTPException:pass
  await self.core.audit(i.guild,i.user.id,'Sugestão decidida',{'suggestion_id':suggestion_id,'decision':decision,'reason':reason});await ep(i,'Decisão registrada.')
 @app_commands.command(name='denuncia_status',description='Atualizar status de denúncia registrada.')
 async def report_status(self,i,report_id:int,status:str,decision_note:str=''):
  if not await self.require_staff(i):return
  if status not in ('reviewing','resolved','rejected'):return await ep(i,'Status inválido: reviewing, resolved ou rejected.')
  r=await self.pool.fetchrow('SELECT * FROM sistemas_reports WHERE id=$1 AND guild_id=$2',report_id,i.guild.id)
  if not r:return await ep(i,'Denúncia não encontrada.')
  await self.pool.execute('UPDATE sistemas_reports SET status=$3,reviewer_id=$4 WHERE id=$1 AND guild_id=$2',report_id,i.guild.id,status,i.user.id);await self.core.audit(i.guild,i.user.id,'Denúncia atualizada',{'report_id':report_id,'status':status,'note':decision_note});await ep(i,'Status da denúncia atualizado.')
 @app_commands.command(name='ban_desbanir',description='Desbanir usuário por ID.')
 async def unban_cmd(self,i,user_id:str,reason:str='Revisão administrativa'):
  if not i.user.guild_permissions.ban_members:return await ep(i,'Ban Members necessário.')
  if not user_id.isdigit():return await ep(i,'ID inválido.')
  try:await i.guild.unban(discord.Object(id=int(user_id)),reason=reason)
  except discord.HTTPException as e:return await ep(i,f'Falha: {str(e)[:200]}')
  case=await self.core.case(i.guild.id,int(user_id),i.user.id,'unban',reason);await self.core.audit(i.guild,i.user.id,'Desbanimento',{'target_id':int(user_id),'case_id':case,'reason':reason},'log_punishment_channel_id',discord.Colour.green());await ep(i,'Desbanimento executado e registrado.')
 @app_commands.command(name='remoto_canais',description='Abrir seletor de servidor e canais para Remote Ops.')
 async def remote_channels(self,i):
  if i.user.id not in env_admins():return await ep(i,'ID não autorizado para Remote Ops.')
  await i.response.send_message(embed=em('NEXUS • REMOTE OPS','Selecione o servidor e canal para ações de mensagem.'),view=RemoteGuildSelect(self.bot),ephemeral=True)
 @tasks.loop(minutes=2)
 async def event_loop(self):
  await self.bot.wait_until_ready()
  rows=await self.pool.fetch("SELECT id,guild_id,channel_id,title,description,winner_count FROM nexus_events WHERE status='open' AND ends_at<=NOW()")
  for r in rows:
   try:
    entries=await self.pool.fetch('SELECT user_id FROM nexus_raffle_entries WHERE event_id=$1',r['id']);winners=random.sample([x['user_id'] for x in entries],min(int(r['winner_count'] or 1),len(entries))) if entries else []
    await self.pool.execute('UPDATE nexus_events SET status=\'closed\' WHERE id=$1',r['id']);g=self.bot.get_guild(r['guild_id']);ch=g.get_channel(r['channel_id']) if g else None
    if ch:await ch.send(embed=em(f'NEXUS • EVENTO #{r["id"]} ENCERRADO',f'Participantes: {len(entries)}\nVencedores: {", ".join(f"<@{x}>" for x in winners) if winners else "Sem participantes"}'))
   except Exception:log.exception('Event ending error id=%s',r['id'])
 @event_loop.before_loop
 async def before_event(self):await self.bot.wait_until_ready()
class EventJoinView(discord.ui.View):
 def __init__(self,eid):super().__init__(timeout=None);self.eid=eid
 @discord.ui.button(label='Participar',style=discord.ButtonStyle.success,custom_id='nexus:event:join')
 async def join(self,i,b):
  cog=i.client.get_cog('NexusExtra');row=await cog.pool.fetchrow("SELECT id FROM nexus_events WHERE id=$1 AND guild_id=$2 AND status='open' AND ends_at>NOW()",self.eid,i.guild.id)
  if not row:return await ep(i,'Inscrições encerradas.')
  await cog.pool.execute('INSERT INTO nexus_raffle_entries(event_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING',self.eid,i.user.id);await ep(i,'Participação registrada; duplicatas são evitadas automaticamente.')
class RemoteGuildSelect(discord.ui.View):
 def __init__(self,bot):super().__init__(timeout=120);self.add_item(RemoteGuildDropdown(bot))
class RemoteGuildDropdown(discord.ui.Select):
 def __init__(self,bot):
  opts=[discord.SelectOption(label=g.name[:100],value=str(g.id),description=f'{g.member_count or 0} membros') for g in bot.guilds[:25]]
  if not opts:opts=[discord.SelectOption(label='Nenhum servidor',value='none')]
  super().__init__(placeholder='Selecione um servidor',options=opts,custom_id='nexus:remote:guildselect')
 async def callback(self,i):
  if i.user.id not in env_admins():return await ep(i,'Acesso negado.')
  if self.values[0]=='none':return await ep(i,'Lista vazia. Use o painel remoto de servidores.')
  g=i.client.get_guild(int(self.values[0]));
  if not g:return await ep(i,'Servidor não encontrado.')
  await i.response.send_message(embed=em('Remote Ops • Canais',f'Servidor: {g.name}'),view=RemoteChannelSelect(g),ephemeral=True)
class RemoteChannelSelect(discord.ui.View):
 def __init__(self,g):super().__init__(timeout=120);self.add_item(RemoteChannelDropdown(g))
class RemoteChannelDropdown(discord.ui.Select):
 def __init__(self,g):
  self.guild_id=g.id;channels=[c for c in g.text_channels[:25] if c.permissions_for(g.me).send_messages]
  options=[discord.SelectOption(label=c.name[:100],value=str(c.id)) for c in channels] or [discord.SelectOption(label='Sem canais autorizados',value='0')]
  super().__init__(placeholder='Selecione canal de texto',options=options,custom_id='nexus:remote:chselect')
 async def callback(self,i):
  if i.user.id not in env_admins():return await ep(i,'Acesso negado.')
  if self.values[0]=='0':return await ep(i,'Nenhum canal enviável encontrado.')
  await i.response.send_modal(RemoteSendModal(self.guild_id,int(self.values[0])))
class RemoteSendModal(discord.ui.Modal,title='Remote Ops • Mensagem'):
 def __init__(self,gid,cid):super().__init__();self.gid=gid;self.cid=cid;self.text=discord.ui.TextInput(label='Mensagem',style=discord.TextStyle.paragraph,max_length=1800);self.add_item(self.text)
 async def on_submit(self,i):
  if i.user.id not in env_admins():return await ep(i,'Acesso negado.')
  g=i.client.get_guild(self.gid);ch=g.get_channel(self.cid) if g else None
  if not ch:return await ep(i,'Canal indisponível.')
  await ch.send(self.text.value,allowed_mentions=discord.AllowedMentions.none());core=i.client.get_cog('Systems');await core.audit(g,i.user.id,'Remote Ops • envio',{'channel_id':ch.id,'message_length':len(self.text.value)});await ep(i,'Mensagem enviada e registrada na auditoria.')
class RecruitmentView(discord.ui.View):
 def __init__(self):super().__init__(timeout=None)
 @discord.ui.button(label='Candidatar-se',style=discord.ButtonStyle.primary,custom_id='nexus:staff:apply')
 async def apply(self,i,b):await i.response.send_modal(RecruitmentModal())
class RecruitmentModal(discord.ui.Modal,title='Nexus Staff • Candidatura'):
 experience=discord.ui.TextInput(label='Experiência',style=discord.TextStyle.paragraph,min_length=20,max_length=1000)
 availability=discord.ui.TextInput(label='Disponibilidade',max_length=300)
 motivation=discord.ui.TextInput(label='Motivação',style=discord.TextStyle.paragraph,min_length=30,max_length=1000)
 async def on_submit(self,i):
  cog=i.client.get_cog('NexusExtra');answers={'experience':self.experience.value,'availability':self.availability.value,'motivation':self.motivation.value}
  aid=await cog.pool.fetchval('INSERT INTO nexus_staff_applications(guild_id,user_id,answers) VALUES($1,$2,$3::jsonb) RETURNING id',i.guild.id,i.user.id,__import__('json').dumps(answers,ensure_ascii=False))
  cfg=await cog.core.config(i.guild.id);ch=i.guild.get_channel(cfg.get('recruitment_channel_id')) if cfg.get('recruitment_channel_id') else None
  if ch:
   e=em(f'NEXUS STAFF • Candidatura #{aid}',f'Candidato: {i.user.mention} (`{i.user.id}`)');e.add_field(name='Experiência',value=self.experience.value[:1000],inline=False);e.add_field(name='Disponibilidade',value=self.availability.value,inline=False);e.add_field(name='Motivação',value=self.motivation.value[:1000],inline=False);await ch.send(embed=e)
  await ep(i,f'Candidatura enviada e salva. Protocolo #{aid}.')
async def _setup_legacy(bot):
 if bot.get_cog('Systems') is None:raise RuntimeError('Systems deve ser carregado antes de comandosextra.')
 if bot.get_cog('NexusExtra') is None:await bot.add_cog(NexusExtra(bot))

# ============================================================================
# NEXUS EXTRA — PUNISHMENT REQUEST PANEL, COMMERCIAL STORE, SOCIAL NOTIFICATIONS
# Official Nexus artwork provided by the server owner.
# ============================================================================
import json as _json
import asyncio as _asyncio
import urllib.request as _urlrequest
import urllib.parse as _urlparse
import xml.etree.ElementTree as _ET
from datetime import datetime as _dt, timezone as _tz

NEXUS_SHIELD = 'https://files.catbox.moe/gsbbt1.png'
NEXUS_BANNER = 'https://files.catbox.moe/9nlwvg.png'
NEXUS_REFERENCE = 'https://files.catbox.moe/8w3qcf.jpg'


def _art_embed(title, description, color=PURPLE, image=NEXUS_BANNER):
    embed = discord.Embed(title=title, description=description, color=color, timestamp=_dt.now(_tz.utc))
    embed.set_thumbnail(url=NEXUS_SHIELD)
    if image:
        embed.set_image(url=image)
    embed.set_footer(text='NEXUS • Sistemas oficiais', icon_url=NEXUS_SHIELD)
    return embed


class PunishmentRequestModal(discord.ui.Modal, title='Nexus • Solicitação de punição'):
    accused = discord.ui.TextInput(label='ID ou menção do acusado', placeholder='ID Discord ou @membro', max_length=100)
    punishment = discord.ui.TextInput(label='Punição solicitada', placeholder='Advertência, timeout, kick, ban…', max_length=100)
    reason = discord.ui.TextInput(label='Motivo e contexto', style=discord.TextStyle.paragraph, min_length=10, max_length=1500)
    evidence = discord.ui.TextInput(label='Link das provas (opcional)', required=False, max_length=500, placeholder='URL de imagem, vídeo ou mensagem')
    duration = discord.ui.TextInput(label='Duração (se aplicável)', required=False, max_length=100, placeholder='Ex.: 1 hora, 7 dias, permanente')

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('NexusExtraPanels')
        if not cog: return await ep(interaction, 'Módulo de solicitações indisponível no momento.')
        accused_id = re.search(r'\d{15,22}', self.accused.value)
        target = accused_id.group(0) if accused_id else self.accused.value.strip()
        rid = await cog.pool.fetchval(
            "INSERT INTO nexus_punishment_requests_extra(guild_id,requester_id,accused,punishment,reason,evidence,duration,status) VALUES($1,$2,$3,$4,$5,$6,$7,'pending') RETURNING id",
            interaction.guild.id, interaction.user.id, target, self.punishment.value.strip(), self.reason.value.strip(), self.evidence.value.strip(), self.duration.value.strip()
        )
        cfg = await cog.pool.fetchrow('SELECT review_channel_id FROM nexus_extra_panel_config WHERE guild_id=$1', interaction.guild.id)
        channel = interaction.guild.get_channel(cfg['review_channel_id']) if cfg and cfg['review_channel_id'] else None
        review_embed = _art_embed(f'⚖️ Solicitação #{rid}', f'**Solicitante:** {interaction.user.mention}\n**Acusado:** {discord.utils.escape_mentions(target)}\n**Punição:** {discord.utils.escape_mentions(self.punishment.value)}\n**Duração:** {discord.utils.escape_mentions(self.duration.value or "Não especificada")}\n\n**Motivo**\n{discord.utils.escape_mentions(self.reason.value)}\n\n**Provas:** {self.evidence.value or "Não fornecidas"}', image=NEXUS_REFERENCE)
        review_embed.add_field(name='Status', value='🟡 Aguardando análise da equipe', inline=False)
        if channel:
            msg = await channel.send(embed=review_embed, view=PunishmentReviewView(rid))
            await cog.pool.execute('UPDATE nexus_punishment_requests_extra SET review_message_id=$2,review_channel_id=$3 WHERE id=$1', rid, msg.id, channel.id)
        await ep(interaction, f'📨 Solicitação enviada para análise. Protocolo **#{rid}**. A staff decidirá se a punição será aplicada.')


class PunishmentRequestPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label='Solicitar punição', emoji='📨', style=discord.ButtonStyle.primary, custom_id='nexus:extra:punishment:open')
    async def open_form(self, interaction, button):
        await interaction.response.send_modal(PunishmentRequestModal())


class PunishmentReviewView(discord.ui.View):
    def __init__(self, request_id: int):
        super().__init__(timeout=None)
        self.request_id = int(request_id)
        self.add_item(discord.ui.Button(label='Aprovar', emoji='✅', style=discord.ButtonStyle.success, custom_id=f'nexus:extra:punish:approve:{self.request_id}'))
        self.add_item(discord.ui.Button(label='Recusar', emoji='❌', style=discord.ButtonStyle.danger, custom_id=f'nexus:extra:punish:deny:{self.request_id}'))
        self.children[0].callback = self.approve
        self.children[1].callback = self.deny
    async def _decision(self, interaction, approved):
        cog = interaction.client.get_cog('NexusExtraPanels')
        cfg = await cog.pool.fetchrow('SELECT reviewer_role_id FROM nexus_extra_panel_config WHERE guild_id=$1', interaction.guild.id)
        role = interaction.guild.get_role(cfg['reviewer_role_id']) if cfg and cfg['reviewer_role_id'] else None
        permitted = interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.moderate_members or (role and role in interaction.user.roles)
        if not permitted: return await ep(interaction, '⛔ Você não possui permissão para revisar solicitações.')
        status = 'approved' if approved else 'denied'
        row = await cog.pool.fetchrow("UPDATE nexus_punishment_requests_extra SET status=$2,reviewer_id=$3,reviewed_at=NOW() WHERE id=$1 AND guild_id=$4 AND status='pending' RETURNING requester_id,accused,punishment,reason", self.request_id, status, interaction.user.id, interaction.guild.id)
        if not row: return await ep(interaction, 'Solicitação já analisada ou não encontrada.')
        try:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green() if approved else discord.Color.red()
            embed.add_field(name='Decisão', value=f'{"✅ Aprovada" if approved else "❌ Recusada"} por {interaction.user.mention}', inline=False)
            await interaction.message.edit(embed=embed, view=None)
        except discord.HTTPException: pass
        try:
            requester = await interaction.guild.fetch_member(row['requester_id'])
            await requester.send(f'Sua solicitação **#{self.request_id}** foi {"aprovada" if approved else "recusada"} pela equipe. A aprovação não aplica a punição automaticamente; a staff precisa executá-la e registrá-la no sistema de moderação.')
        except (discord.HTTPException, discord.NotFound): pass
        await ep(interaction, 'Decisão registrada. A aprovação **não executa a punição automaticamente**; aplique-a no sistema de moderação e registre o caso.')
    async def approve(self, interaction): await self._decision(interaction, True)
    async def deny(self, interaction): await self._decision(interaction, False)


class NexusStoreBuyButton(discord.ui.Button):
    def __init__(self, product_id, label):
        super().__init__(label=f'Comprar • {label[:70]}', style=discord.ButtonStyle.success, custom_id=f'nexus:extra:store:buy:{product_id}')
        self.product_id = int(product_id)
    async def callback(self, interaction):
        cog = interaction.client.get_cog('NexusExtraPanels')
        product = await cog.pool.fetchrow('SELECT * FROM nexus_store_products_extra WHERE id=$1 AND guild_id=$2 AND active=TRUE', self.product_id, interaction.guild.id)
        if not product: return await ep(interaction, 'Este produto não está mais disponível.')
        if product['stock'] == 0: return await ep(interaction, 'Produto sem estoque no momento.')
        await interaction.response.send_modal(StoreOrderModal(self.product_id, product['name']))


class NexusStorePanelView(discord.ui.View):
    def __init__(self, product_rows):
        super().__init__(timeout=None)
        for row in product_rows[:20]:
            self.add_item(NexusStoreBuyButton(row['id'], row['name']))


class StoreOrderModal(discord.ui.Modal):
    def __init__(self, product_id, product_name):
        super().__init__(title=f'Pedido • {product_name[:40]}')
        self.product_id = int(product_id)
        self.quantity = discord.ui.TextInput(label='Quantidade', default='1', min_length=1, max_length=2)
        self.details = discord.ui.TextInput(label='Detalhes do pedido (opcional)', style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.add_item(self.quantity); self.add_item(self.details)
    async def on_submit(self, interaction):
        cog = interaction.client.get_cog('NexusExtraPanels')
        try: qty = int(self.quantity.value)
        except ValueError: return await ep(interaction, 'Quantidade inválida. Digite um número entre 1 e 20.')
        if qty < 1 or qty > 20: return await ep(interaction, 'Quantidade permitida: 1 a 20.')
        async with cog.pool.acquire() as conn:
            async with conn.transaction():
                product = await conn.fetchrow('SELECT * FROM nexus_store_products_extra WHERE id=$1 AND guild_id=$2 AND active=TRUE FOR UPDATE', self.product_id, interaction.guild.id)
                if not product: return await ep(interaction, 'Produto indisponível.')
                if product['stock'] >= 0 and product['stock'] < qty: return await ep(interaction, f'Estoque insuficiente. Disponível: {product["stock"]}.')
                total = product['price_cents'] * qty
                oid = await conn.fetchval("INSERT INTO nexus_store_orders_extra(guild_id,product_id,buyer_id,quantity,total_cents,details,status) VALUES($1,$2,$3,$4,$5,$6,'pending') RETURNING id", interaction.guild.id, self.product_id, interaction.user.id, qty, total, self.details.value.strip())
                if product['stock'] >= 0: await conn.execute('UPDATE nexus_store_products_extra SET stock=stock-$2 WHERE id=$1', self.product_id, qty)
        cfg = await cog.pool.fetchrow('SELECT order_channel_id FROM nexus_extra_panel_config WHERE guild_id=$1', interaction.guild.id)
        order_channel = interaction.guild.get_channel(cfg['order_channel_id']) if cfg and cfg['order_channel_id'] else None
        if order_channel:
            order_embed = _art_embed(f'🧾 Pedido #{oid}', f'**Comprador:** {interaction.user.mention}\n**Produto:** {product["name"]}\n**Quantidade:** {qty}\n**Total:** R$ {total/100:.2f}\n**Detalhes:** {self.details.value or "—"}\n\n**Status:** 🟡 Pendente de pagamento/atendimento', image=NEXUS_REFERENCE)
            order_embed.add_field(name='Pagamento', value='Pagamento precisa ser confirmado manualmente. O bot não confirma Pix ou pagamento automaticamente.', inline=False)
            await order_channel.send(embed=order_embed)
        await ep(interaction, f'Pedido **#{oid}** criado! Total **R$ {total/100:.2f}**. A equipe enviará instruções de pagamento. O pedido ainda não está pago.')


class NexusExtraPanels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        systems = bot.get_cog('Systems')
        self.pool = systems.pool if systems else None
        if self.pool is None: raise RuntimeError('Carregue sistemas antes de comandos_extra.')
        self._twitch_token = None
        self._twitch_token_expiry = 0
        self.social_poll.start()
    async def cog_load(self):
        await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_extra_panel_config(guild_id BIGINT PRIMARY KEY,review_channel_id BIGINT,reviewer_role_id BIGINT,store_channel_id BIGINT,order_channel_id BIGINT,social_channel_id BIGINT,social_role_id BIGINT)")
        await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_punishment_requests_extra(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,requester_id BIGINT NOT NULL,accused TEXT NOT NULL,punishment TEXT NOT NULL,reason TEXT NOT NULL,evidence TEXT,duration TEXT,status TEXT NOT NULL DEFAULT 'pending',reviewer_id BIGINT,reviewed_at TIMESTAMPTZ,review_message_id BIGINT,review_channel_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_store_products_extra(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,image_url TEXT,price_cents INTEGER NOT NULL CHECK(price_cents>0),stock INTEGER NOT NULL DEFAULT -1,active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_store_orders_extra(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,product_id BIGINT NOT NULL,buyer_id BIGINT NOT NULL,quantity INTEGER NOT NULL,total_cents INTEGER NOT NULL,details TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        await self.pool.execute("CREATE TABLE IF NOT EXISTS nexus_social_sources_extra(id BIGSERIAL PRIMARY KEY,guild_id BIGINT NOT NULL,platform TEXT NOT NULL,profile_name TEXT NOT NULL,feed_url TEXT NOT NULL,channel_id BIGINT NOT NULL,role_id BIGINT,last_seen TEXT,active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),UNIQUE(guild_id,platform,profile_name))")
        self.bot.add_view(PunishmentRequestPanelView())
        pending = await self.pool.fetch("SELECT id,review_message_id FROM nexus_punishment_requests_extra WHERE status='pending' AND review_message_id IS NOT NULL")
        for row in pending:
            self.bot.add_view(PunishmentReviewView(row['id']), message_id=row['review_message_id'])
        for guild in self.bot.guilds:
            products = await self.pool.fetch('SELECT id,name FROM nexus_store_products_extra WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 20', guild.id)
            # Product button IDs are persistent and bound to the individual published panel message.
            # Views are rehydrated from the panel message where the panel is published; global registration supports interactions too.
            for product in products: self.bot.add_view(NexusStorePanelView([product]))
    def cog_unload(self): self.social_poll.cancel()
    async def staff_check(self, interaction):
        if interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator: return True
        core = self.bot.get_cog('Systems')
        try:
            cfg = await core.config(interaction.guild.id)
            from sistemas import staff
            return staff(interaction.user, cfg)
        except Exception: return False
    async def ensure_config(self, guild_id):
        await self.pool.execute('INSERT INTO nexus_extra_panel_config(guild_id) VALUES($1) ON CONFLICT DO NOTHING', guild_id)

    @app_commands.command(name='painel_punicoes', description='Publicar o painel Nexus para solicitar análise de punição.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def publish_punishment_panel(self, interaction, review_channel: discord.TextChannel, reviewer_role: discord.Role = None, panel_channel: discord.TextChannel = None):
        await self.ensure_config(interaction.guild.id)
        await self.pool.execute('UPDATE nexus_extra_panel_config SET review_channel_id=$2,reviewer_role_id=$3 WHERE guild_id=$1', interaction.guild.id, review_channel.id, reviewer_role.id if reviewer_role else None)
        target = panel_channel or interaction.channel
        e = _art_embed('⚖️ NEXUS • CENTRAL DE SOLICITAÇÕES', 'Precisa reportar uma infração e solicitar uma análise da equipe?\n\nClique no botão abaixo e preencha o formulário com informações claras e provas, se disponíveis.\n\n> Solicitações são analisadas pela staff. Enviar um pedido não garante aplicação de punição.', image=NEXUS_BANNER)
        await target.send(embed=e, view=PunishmentRequestPanelView())
        await ep(interaction, f'Painel publicado em {target.mention}. Canal de análise: {review_channel.mention}.')

    @app_commands.command(name='loja_produto_add', description='Cadastrar um produto comercial na loja Nexus.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def store_add(self, interaction, name: str, price_brl: app_commands.Range[float, 0.01, 1000000], stock: int, description: str, image_url: str = ''):
        if stock < -1: return await ep(interaction, 'Estoque use -1 para ilimitado ou 0+ para quantidade finita.')
        if image_url and not image_url.startswith(('https://','http://')): return await ep(interaction, 'URL da imagem precisa começar com https:// ou http://.')
        cents = round(price_brl * 100)
        pid = await self.pool.fetchval('INSERT INTO nexus_store_products_extra(guild_id,name,description,image_url,price_cents,stock) VALUES($1,$2,$3,$4,$5,$6) RETURNING id', interaction.guild.id, name.strip(), description.strip(), image_url, cents, stock)
        await ep(interaction, f'Produto **#{pid} • {name}** cadastrado por **R$ {price_brl:.2f}**. Use `/loja_publicar` para exibir o catálogo.')

    @app_commands.command(name='loja_produto_remover', description='Desativar produto comercial da loja Nexus.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def store_remove(self, interaction, product_id: int):
        result = await self.pool.execute('UPDATE nexus_store_products_extra SET active=FALSE WHERE id=$1 AND guild_id=$2', product_id, interaction.guild.id)
        if result.endswith('0'): return await ep(interaction, 'Produto não encontrado.')
        await ep(interaction, f'Produto #{product_id} desativado e removido dos novos catálogos.')

    @app_commands.command(name='loja_publicar', description='Publicar catálogo comercial Nexus com botões de pedido.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def store_publish(self, interaction, order_channel: discord.TextChannel, panel_channel: discord.TextChannel = None):
        await self.ensure_config(interaction.guild.id)
        await self.pool.execute('UPDATE nexus_extra_panel_config SET order_channel_id=$2,store_channel_id=$3 WHERE guild_id=$1', interaction.guild.id, order_channel.id, (panel_channel or interaction.channel).id)
        products = await self.pool.fetch('SELECT id,name,description,image_url,price_cents,stock FROM nexus_store_products_extra WHERE guild_id=$1 AND active=TRUE ORDER BY id LIMIT 20', interaction.guild.id)
        if not products: return await ep(interaction, 'Cadastre produtos primeiro usando `/loja_produto_add`.')
        panel = _art_embed('🛍️ NEXUS • LOJA OFICIAL', 'Escolha um produto para abrir seu pedido.\n\n**Atenção:** pedidos não significam pagamento confirmado; a equipe confirma manualmente.', image=NEXUS_BANNER)
        for p in products:
            image_line = f'[Imagem do produto]({p["image_url"]})' if p['image_url'] else ''
            panel.add_field(name=f'#{p["id"]} • {p["name"]} • R$ {p["price_cents"]/100:.2f}', value=f'{p["description"][:220]}\nEstoque: {"Ilimitado" if p["stock"]<0 else p["stock"]}\n{image_line}', inline=False)
        view = NexusStorePanelView(products)
        target = panel_channel or interaction.channel
        await target.send(embed=panel, view=view)
        await ep(interaction, f'Catálogo publicado em {target.mention}; pedidos vão para {order_channel.mention}.')

    @app_commands.command(name='loja_pedidos_extra', description='Consultar pedidos comerciais recentes.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def store_orders(self, interaction, status: str = 'pending'):
        if status not in ('pending','paid','delivered','cancelled','all'): return await ep(interaction, 'Status: pending, paid, delivered, cancelled ou all.')
        q = 'SELECT o.id,o.buyer_id,o.product_id,o.quantity,o.total_cents,o.status,o.created_at,p.name FROM nexus_store_orders_extra o JOIN nexus_store_products_extra p ON p.id=o.product_id WHERE o.guild_id=$1'
        args=[interaction.guild.id]
        if status!='all':q+=' AND o.status=$2';args.append(status)
        rows=await self.pool.fetch(q+' ORDER BY o.id DESC LIMIT 20',*args)
        embed=_art_embed('🧾 NEXUS • PEDIDOS',f'{len(rows)} pedidos recentes • filtro **{status}**',image=NEXUS_REFERENCE)
        for r in rows: embed.add_field(name=f'#{r["id"]} • {r["name"]} • {r["status"]}',value=f'Comprador: <@{r["buyer_id"]}>\nQtd: {r["quantity"]} • Total R$ {r["total_cents"]/100:.2f}',inline=False)
        await ep(interaction,embed=embed)

    @app_commands.command(name='loja_pedido_status', description='Atualizar status de pedido comercial (staff).')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def store_order_status(self, interaction, order_id: int, status: str):
        if status not in ('pending','paid','delivered','cancelled'): return await ep(interaction, 'Status aceitos: pending, paid, delivered, cancelled.')
        res=await self.pool.execute('UPDATE nexus_store_orders_extra SET status=$3,updated_at=NOW() WHERE id=$1 AND guild_id=$2',order_id,interaction.guild.id,status)
        if res.endswith('0'): return await ep(interaction,'Pedido não encontrado.')
        await ep(interaction,f'Pedido #{order_id} atualizado para **{status}**. Confirmação de pagamento deve ser manual.')

    @app_commands.command(name='social_adicionar', description='Adicionar perfil/feed para monitoramento e notificações.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_add(self, interaction, platform: str, profile_name: str, feed_url: str, channel: discord.TextChannel, role: discord.Role = None):
        platform = platform.lower().strip()
        if platform not in ('youtube','twitch','instagram','tiktok'): return await ep(interaction, 'Plataformas: youtube, twitch, instagram ou tiktok.')
        if not feed_url.startswith(('https://','http://')): return await ep(interaction,'Feed URL precisa ser HTTP/HTTPS. Para Instagram/TikTok, use um feed público compatível (ex.: RSSHub); não há garantia de acesso a todo perfil.')
        await self.ensure_config(interaction.guild.id)
        await self.pool.execute('UPDATE nexus_extra_panel_config SET social_channel_id=$2,social_role_id=$3 WHERE guild_id=$1',interaction.guild.id,channel.id,role.id if role else None)
        try:
            await self.pool.execute('INSERT INTO nexus_social_sources_extra(guild_id,platform,profile_name,feed_url,channel_id,role_id) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(guild_id,platform,profile_name) DO UPDATE SET feed_url=EXCLUDED.feed_url,channel_id=EXCLUDED.channel_id,role_id=EXCLUDED.role_id,active=TRUE',interaction.guild.id,platform,profile_name.strip(),feed_url,channel.id,role.id if role else None)
        except Exception as exc: log.exception('Social feed registration failed');return await ep(interaction,'Não foi possível cadastrar feed. Confira a URL e tente novamente.')
        await ep(interaction,f'📡 Perfil **{profile_name}** ({platform}) monitorado. Canal: {channel.mention}; cargo: {role.mention if role else "sem cargo"}.')

    @app_commands.command(name='social_remover', description='Remover perfil do monitoramento social.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_remove(self, interaction, source_id: int):
        res=await self.pool.execute('UPDATE nexus_social_sources_extra SET active=FALSE WHERE id=$1 AND guild_id=$2',source_id,interaction.guild.id)
        if res.endswith('0'):return await ep(interaction,'Perfil não encontrado.')
        await ep(interaction,'Perfil removido do monitoramento.')

    @app_commands.command(name='social_lista', description='Listar perfis monitorados e feeds.')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_list(self, interaction):
        rows=await self.pool.fetch('SELECT id,platform,profile_name,feed_url,channel_id,role_id FROM nexus_social_sources_extra WHERE guild_id=$1 AND active=TRUE ORDER BY id',interaction.guild.id)
        embed=_art_embed('📡 NEXUS • MONITORAMENTO SOCIAL',f'{len(rows)} perfil(is) ativo(s)',image=NEXUS_REFERENCE)
        for row in rows:
            role_mention = f'<@&{row["role_id"]}>' if row['role_id'] else '—'
            embed.add_field(name=f'#{row["id"]} • {row["platform"].upper()} • {row["profile_name"]}', value=f'Feed: {row["feed_url"][:180]}\nCanal: <#{row["channel_id"]}> • Cargo: {role_mention}', inline=False)
        await ep(interaction,embed=embed)

    @tasks.loop(minutes=5)
    async def social_poll(self):
        await self.bot.wait_until_ready()
        sources=await self.pool.fetch('SELECT * FROM nexus_social_sources_extra WHERE active=TRUE')
        for source in sources:
            try:
                if source['platform'] == 'twitch':
                    stream = await _asyncio.to_thread(self._twitch_stream, source['profile_name'])
                    guild = self.bot.get_guild(source['guild_id'])
                    channel = guild.get_channel(source['channel_id']) if guild else None
                    if not stream:
                        if source['last_seen']:
                            await self.pool.execute('UPDATE nexus_social_sources_extra SET last_seen=NULL WHERE id=$1', source['id'])
                        continue
                    stream_id = str(stream['id'])
                    if source['last_seen'] == stream_id: continue
                    if channel:
                        role_text = f'<@&{source["role_id"]}> ' if source['role_id'] else ''
                        embed = _art_embed('🟣 NEXUS • LIVE NA TWITCH', f'**{source["profile_name"]}** está ao vivo!\n\n**{stream.get("title", "Live iniciada")}**\nCategoria: {stream.get("game_name") or "—"}\n[Assistir à transmissão](https://www.twitch.tv/{source["profile_name"]})', image=NEXUS_BANNER)
                        await channel.send(content=role_text, embed=embed, allowed_mentions=discord.AllowedMentions(roles=[discord.Object(id=source['role_id'])] if source['role_id'] else []))
                    await self.pool.execute('UPDATE nexus_social_sources_extra SET last_seen=$2 WHERE id=$1', source['id'], stream_id)
                    continue
                xml=await _asyncio.to_thread(self._fetch_feed,source['feed_url'])
                root=_ET.fromstring(xml)
                entries=[]
                # RSS and Atom support
                for item in root.findall('.//item'):
                    title=item.findtext('title') or source['profile_name']
                    link=item.findtext('link') or ''
                    guid=item.findtext('guid') or link or title
                    media_ns='{http://search.yahoo.com/mrss/}'
                    thumb_el=item.find(f'{media_ns}thumbnail')
                    thumbnail=thumb_el.attrib.get('url','') if thumb_el is not None else ''
                    entries.append((guid,title,link,thumbnail))
                atom_ns={'a':'http://www.w3.org/2005/Atom'}
                for item in root.findall('.//a:entry',atom_ns):
                    title=item.findtext('a:title',namespaces=atom_ns) or source['profile_name']
                    link_el=item.find('a:link',atom_ns);link=link_el.attrib.get('href','') if link_el is not None else ''
                    guid=item.findtext('a:id',namespaces=atom_ns) or link or title
                    entries.append((guid,title,link,''))
                entries=entries[:5]
                if not entries:continue
                last=source['last_seen']
                # On first run, set latest marker and do not spam historic entries.
                if not last:
                    await self.pool.execute('UPDATE nexus_social_sources_extra SET last_seen=$2 WHERE id=$1',source['id'],entries[0][0]);continue
                fresh=[]
                for entry in entries:
                    if entry[0]==last:break
                    fresh.append(entry)
                if fresh:
                    fresh.reverse()
                    guild=self.bot.get_guild(source['guild_id']);channel=guild.get_channel(source['channel_id']) if guild else None
                    if channel:
                        for guid,title,link,thumbnail in fresh:
                            platform_emoji={'youtube':'▶️','twitch':'🟣','instagram':'📸','tiktok':'🎵'}.get(source['platform'],'📣')
                            embed=_art_embed(f'{platform_emoji} NOVO CONTEÚDO • {source["platform"].upper()}',f'**{source["profile_name"]}** publicou conteúdo novo!\n\n[{discord.utils.escape_markdown(title[:250])}]({link})' if link else f'**{source["profile_name"]}**\n{title[:250]}',image=thumbnail or NEXUS_BANNER)
                            role_text=f'<@&{source["role_id"]}> ' if source['role_id'] else ''
                            await channel.send(content=role_text,embed=embed,allowed_mentions=discord.AllowedMentions(roles=[discord.Object(id=source['role_id'])] if source['role_id'] else []))
                    await self.pool.execute('UPDATE nexus_social_sources_extra SET last_seen=$2 WHERE id=$1',source['id'],entries[0][0])
            except Exception as exc:
                log.warning('Social poll source %s error: %s',source['id'],type(exc).__name__)
    @social_poll.before_loop
    async def before_social_poll(self): await self.bot.wait_until_ready()
    def _twitch_stream(self, login):
        client_id=os.getenv('TWITCH_CLIENT_ID','').strip()
        client_secret=os.getenv('TWITCH_CLIENT_SECRET','').strip()
        if not client_id or not client_secret:
            raise RuntimeError('TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET não configurados')
        now=_dt.now(_tz.utc).timestamp()
        if not self._twitch_token or now >= self._twitch_token_expiry:
            payload=_urlparse.urlencode({'client_id':client_id,'client_secret':client_secret,'grant_type':'client_credentials'}).encode()
            req=_urlrequest.Request('https://id.twitch.tv/oauth2/token',data=payload,headers={'Content-Type':'application/x-www-form-urlencoded'})
            with _urlrequest.urlopen(req,timeout=20) as response: token_data=_json.loads(response.read().decode())
            self._twitch_token=token_data['access_token'];self._twitch_token_expiry=now+int(token_data.get('expires_in',3600))-60
        req=_urlrequest.Request('https://api.twitch.tv/helix/streams?user_login='+_urlparse.quote(login),headers={'Client-ID':client_id,'Authorization':'Bearer '+self._twitch_token})
        with _urlrequest.urlopen(req,timeout=20) as response: data=_json.loads(response.read().decode())
        return data.get('data',[None])[0]

    @staticmethod
    def _fetch_feed(url):
        req=_urlrequest.Request(url,headers={'User-Agent':'NexusDiscordBot/1.0 (RSS monitor)'})
        with _urlrequest.urlopen(req,timeout=20) as response:return response.read().decode('utf-8','replace')

async def setup(bot):
    await _setup_legacy(bot)
    if bot.get_cog('NexusExtraPanels') is None:
        await bot.add_cog(NexusExtraPanels(bot))

async def teardown(bot):
    for cog_name in ('NexusExtra','NexusExtraPanels'):
        cog=bot.get_cog(cog_name)
        if cog: await bot.remove_cog(cog_name)
