# 🔐 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random, os, json, sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────
# 📊 Google Sheets 인증
# ─────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
SHEET_KEY = os.getenv("SHEET_KEY")

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds_dict = json.loads(GOOGLE_CREDS)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gclient = gspread.authorize(creds)

def ws(title: str):
    return gclient.open_by_key(SHEET_KEY).worksheet(title)

# ─────────────────────────────────────────────
# 🧰 유틸
# ─────────────────────────────────────────────
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

def _find_row_by_id(sh, user_id: str):
    col_a = sh.col_values(1)
    for idx, v in enumerate(col_a, start=1):
        if (v or "").strip() == user_id:
            return idx
    return None

def ensure_user_row(user_id: str, user_name: str):
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        sh.append_row([user_id, user_name, 100, now_kst_str()])
    return True

def get_balance(user_id: str, user_name: str):
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        ensure_user_row(user_id, user_name)
        return 100
    return int(sh.cell(row, 3).value or 0)

def set_balance(user_id: str, user_name: str, value: int):
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        ensure_user_row(user_id, user_name)
        row = _find_row_by_id(sh, user_id)
    value = max(int(value), 0)
    sh.update_acell(f"C{row}", value)
    sh.update_acell(f"D{row}", now_kst_str())
    return value

def add_balance(user_id: str, user_name: str, delta: int):
    cur = get_balance(user_id, user_name)
    return set_balance(user_id, user_name, cur + delta)

# ─────────────────────────────────────────────
# ♣ 덱 관리
# ─────────────────────────────────────────────
channel_decks = {}
suits = ['♠', '♥', '♦', '♣']
ranks = ['A'] + [str(i) for i in range(2, 11)] + ['J', 'Q', 'K']
full_deck = [f"{s}{r}" for s in suits for r in ranks]

def shuffle_decks(cid):
    channel_decks[cid] = {
        "blackjack": random.sample(full_deck, len(full_deck)),
        "blind": random.sample(full_deck, len(full_deck))
    }

def ensure_channel(cid):
    if cid not in channel_decks:
        shuffle_decks(cid)

# ─────────────────────────────────────────────
# 세션 저장
# ─────────────────────────────────────────────
blackjack_sessions = {}
blind_sessions = {}

# ─────────────────────────────────────────────
# 명령
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f"✅ Logged in as {bot.user}")

@bot.command()
async def 세팅(ctx):
    ensure_channel(str(ctx.channel.id))
    await ctx.send("게임을 선택하세요.", view=GameMenu())

@bot.command()
async def 유저(ctx):
    uid, uname = str(ctx.author.id), ctx.author.display_name
    ensure_user_row(uid, uname)
    await ctx.send(f"✅ {uname} 등록 완료 (소지금: {get_balance(uid, uname)})")

# ─────────────────────────────────────────────
# 🎮 메인 메뉴
# ─────────────────────────────────────────────
class GameMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MenuButton("블랙잭", "bj", discord.ButtonStyle.danger, 0))
        self.add_item(MenuButton("블라인드 블랙잭", "blind", discord.ButtonStyle.danger, 0))
        self.add_item(MenuButton("가위바위보", "rps", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("홀짝", "odd", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("야바위", "shell", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("슬롯머신", "slot", discord.ButtonStyle.success, 2))
        self.add_item(MenuButton("다이스", "dice", discord.ButtonStyle.success, 2))
        self.add_item(MenuButton("유저 등록", "user", discord.ButtonStyle.secondary, 4))

class MenuButton(Button):
    def __init__(self, label, custom_id, style, row):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)

    async def callback(self, inter):
        cid = str(inter.channel.id)
        ensure_channel(cid)

        if self.custom_id == "user":
            uid, uname = str(inter.user.id), inter.user.display_name
            ensure_user_row(uid, uname)
            await inter.response.send_message(f"✅ {uname} 등록됨.")
            return

        if self.custom_id == "bj":
            if cid in blackjack_sessions or cid in blind_sessions:
                await inter.response.send_message("⚠️ 이미 게임이 진행 중입니다.", ephemeral=True)
                return
            await inter.response.send_message("🃏 블랙잭 인원 선택", view=PlayerCountSelectView("bj"))
            return

        if self.custom_id == "blind":
            if cid in blackjack_sessions or cid in blind_sessions:
                await inter.response.send_message("⚠️ 이미 게임이 진행 중입니다.", ephemeral=True)
                return
            await inter.response.send_message("🃏 블라인드 블랙잭 인원 선택", view=PlayerCountSelectView("blind"))
            return

        if self.custom_id == "rps":
            await inter.response.send_message(f"✂️ 결과: {random.choice(['가위','바위','보'])}")
        elif self.custom_id == "odd":
            await inter.response.send_message(f"⚪ 결과: {'홀' if random.randint(1,6)%2 else '짝'}")
        elif self.custom_id == "shell":
            await inter.response.send_message(f"🎲 야바위: {random.choice(['OXX','XOX','XXO'])}")
        elif self.custom_id == "slot":
            s = [random.choice(['❤️','💔','💖','💝','🔴','🔥','🦋','💥']) for _ in range(3)]
            msg = "💥 잭팟!" if len(set(s))==1 else "💎 더블!" if len(set(s))==2 else "❌ 꽝!"
            await inter.response.send_message(" ".join(s)+"\n"+msg)
        elif self.custom_id == "dice":
            await inter.response.send_message(f"{inter.user.mention} 🎲 {random.randint(1,6)}")

# ─────────────────────────────────────────────
# 인원 선택
# ─────────────────────────────────────────────
class PlayerCountSelectView(View):
    def __init__(self, mode):
        super().__init__(timeout=None)
        self.mode = mode
        for i in range(2,5):
            self.add_item(PlayerCountButton(i, mode))

class PlayerCountButton(Button):
    def __init__(self, count, mode):
        super().__init__(label=f"{count}명", style=discord.ButtonStyle.primary)
        self.count, self.mode = count, mode

    async def callback(self, inter):
        cid = str(inter.channel.id)
        deck = channel_decks[cid]["blackjack" if self.mode=="bj" else "blind"]
        if self.mode=="bj":
            blackjack_sessions[cid] = BlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블랙잭({self.count}명) 세션 생성! `!참가 금액`으로 참가하세요.")
        else:
            blind_sessions[cid] = BlindBlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블라인드 블랙잭({self.count}명) 세션 생성! `!참가 금액`으로 참가하세요.")

# ─────────────────────────────────────────────
# 블랙잭 세션
# ─────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, cid, deck, max_players):
        self.cid, self.deck, self.max_players = cid, deck, max_players
        self.players, self.ace_values, self.actions = {}, {}, {}
        self.stayed, self.busted, self.bets = set(), set(), {}
        self.started = False

    def deal_initial(self, uid):
        if uid not in self.players:
            self.players[uid] = [self.deck.pop(), self.deck.pop()]
            self.ace_values[uid] = {}
            self.actions[uid] = False
        return self.players[uid]

    def score(self, uid):
        total = 0
        for i,c in enumerate(self.players[uid]):
            r=c[1:]
            if r in ["J","Q","K"]: total+=10
            elif r=="A": total+=self.ace_values.get(uid,{}).get(i,11)
            else: total+=int(r)
        return total

    def hit(self, uid):
        card=self.deck.pop(); self.players[uid].append(card); self.actions[uid]=True; return card
    def stay(self, uid): self.stayed.add(uid); self.actions[uid]=True
    def everyone_joined(self): return len(self.players)==self.max_players and len(self.bets)==self.max_players
    def everyone_acted(self): return all(self.actions.get(u) or u in self.busted for u in self.players)
    def reset_actions(self): [self.actions.update({u:False}) for u in self.players if u not in self.stayed|self.busted]
    def is_finished(self): return all(u in self.stayed or self.score(u)>21 for u in self.players)

# ─────────────────────────────────────────────
# 블라인드 블랙잭 세션
# ─────────────────────────────────────────────

class BlindBlackjackSession:
    def __init__(self, cid, deck, max_players):
        self.cid, self.deck, self.max_players = cid, deck, max_players
        self.players, self.actions = {}, {}
        self.stayed, self.busted, self.bets = set(), set(), {}
        self.started = False
        self.hidden_info = {}  # uid: {"cards": [...], "score": int}

    def deal_initial(self, uid):
        if uid not in self.players:
            cards = [self.deck.pop(), self.deck.pop()]
            self.players[uid] = cards
            self.hidden_info[uid] = {
                "cards": cards,
                "score": self.score_from_cards(cards)
            }
            self.actions[uid] = False
        return self.players[uid]

    def score_from_cards(self, cards):
        total = 0
        for c in cards:
            r = c[1:]
            if r in ["J", "Q", "K"]:
                total += 10
            elif r == "A":
                total += 1
            else:
                total += int(r)
        return total

    def score(self, uid):
        return self.hidden_info[uid]["score"]

    def hit(self, uid):
        c = self.deck.pop()
        self.players[uid].append(c)
        self.actions[uid] = True
        self.hidden_info[uid]["cards"].append(c)
        self.hidden_info[uid]["score"] = self.score_from_cards(self.hidden_info[uid]["cards"])
        return c

    def stay(self, uid):
        self.stayed.add(uid)
        self.actions[uid] = True

    def everyone_joined(self):
        return len(self.players) == self.max_players and len(self.bets) == self.max_players

    def everyone_acted(self):
        return all(self.actions.get(u) or u in self.busted for u in self.players)

    def reset_actions(self):
        for u in self.players:
            if u not in self.stayed and u not in self.busted:
                self.actions[u] = False

    def is_finished(self):
        return all(u in self.stayed or self.score(u) > 21 for u in self.players)


# ─────────────────────────────────────────────
# 참가 명령
# ─────────────────────────────────────────────
@bot.command()
async def 참가(ctx, 금액:str=None):
    cid, uid, uname = str(ctx.channel.id), str(ctx.author.id), ctx.author.display_name
    sess=None; mode=None
    if cid in blackjack_sessions: sess=blackjack_sessions[cid]; mode="bj"
    elif cid in blind_sessions: sess=blind_sessions[cid]; mode="blind"
    else:
        await ctx.send("❌ 세션이 없습니다."); return
    if sess.started: await ctx.send("⚠️ 이미 시작됨."); return
    if not 금액 or not 금액.isdigit(): await ctx.send("!참가 금액 (숫자)"); return
    bet=int(금액)
    if bet>get_balance(uid,uname): await ctx.send("❌ 소지금 부족."); return
    sess.bets[uid]=bet
    if uid not in sess.players:
        sess.players[uid] = []  # 플레이어 등록
    await ctx.send(f"✅ {uname} 참가 — 베팅 {bet}")

    if sess.everyone_joined():
        sess.started = True
        await ctx.send(f"✅ 참가자({sess.max_players}명) 전원 참가 완료!\n🃏 첫 카드 분배를 시작합니다...")

        # 🎴 카드 분배 (모두에게 2장씩)
        for u in sess.bets:
            sess.deal_initial(u)
    
        # 블랙잭 모드 - 카드 공개
        if mode == "bj":
            for u in sess.players:
                member = ctx.guild.get_member(int(u))
                name = member.display_name if member else f"UID:{u}"
                cards = " ".join(sess.players[u])
                score = sess.score(u)
                await ctx.send(f"**{name}** 님의 첫 패: {cards} (합계 {score})")
    
        # 블라인드 블랙잭 모드 - 완전 비공개
        else:
            for u in sess.players:
                member = ctx.guild.get_member(int(u))
                name = member.display_name if member else f"UID:{u}"
                await ctx.send(f"**{name}** 님의 첫 패 분배 완료. (카드 및 합계 비공개)")
    
        # 🎮 참가자 안내
        names = [ctx.guild.get_member(int(u)).display_name for u in sess.bets]
        await ctx.send(f"🎮 게임 시작!\n참가자: {', '.join(names)}")
    
        # 🧭 첫 라운드 히트/스테이는 카드 분배 후 자동 시작
        for u in sess.players:
            # 자동 카드 분배가 끝나고 나서 첫 차례부터 버튼 생성
            if mode == "bj":
                await ctx.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))
            else:
                await ctx.send(f"<@{u}> 님 차례입니다.", view=BlindPlayView(target_uid=u))

# ─────────────────────────────────────────────
# ♠ 블랙잭 플레이 버튼
# ─────────────────────────────────────────────
class BlackjackPlayView(View):
    def __init__(self, target_uid):
        super().__init__(timeout=None)
        self.target_uid=target_uid
        self.add_item(BJHitButton())
        self.add_item(BJStayButton())

class BJHitButton(Button):
    def __init__(self): super().__init__(label="히트",style=discord.ButtonStyle.success)
    async def callback(self, inter):
        cid,uid,uname=str(inter.channel.id),str(inter.user.id),inter.user.display_name
        if cid not in blackjack_sessions: await inter.response.send_message("세션 없음",ephemeral=True);return
        sess=blackjack_sessions[cid]
        if uid!=self.view.target_uid: await inter.response.send_message("⛔ 본인만 조작",ephemeral=True);return
        card=sess.hit(uid); sc=sess.score(uid)
        if card[1:]=="A":
            await inter.channel.send(f"{uname} 새 카드 {card} — A값 선택",view=AceChoiceView(uid,len(sess.players[uid])-1));return
        if sc==21:
            await inter.channel.send(f"🎉 {uname} 블랙잭! (합계 21)"); sess.stay(uid); sess.actions[uid]=True; await settle_and_end(inter,"bj",sess);return
        if sc>21:
            sess.busted.add(uid); await inter.channel.send(f"💥 {uname} 버스트! (합계 {sc})")
        else:
            await inter.channel.send(f"{uname} → {' '.join(sess.players[uid])} (합계 {sc})")
        sess.actions[uid]=True
        if sess.everyone_acted():
            if sess.is_finished(): await settle_and_end(inter,"bj",sess)
            else:
                sess.reset_actions()
                for u in sess.players:
                    if u not in sess.stayed|sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.",view=BlackjackPlayView(target_uid=u))

class BJStayButton(Button):
    def __init__(self): super().__init__(label="스테이",style=discord.ButtonStyle.danger)
    async def callback(self, inter):
        cid,uid,uname=str(inter.channel.id),str(inter.user.id),inter.user.display_name
        if cid not in blackjack_sessions: await inter.response.send_message("세션 없음",ephemeral=True);return
        sess=blackjack_sessions[cid]
        if uid!=self.view.target_uid: await inter.response.send_message("⛔ 본인만 조작",ephemeral=True);return
        sess.stay(uid); sc=sess.score(uid)
        await inter.channel.send(f"{uname} 스테이 (합계 {sc})")
        if sess.everyone_acted():
            if sess.is_finished(): await settle_and_end(inter,"bj",sess)
            else:
                sess.reset_actions()
                for u in sess.players:
                    if u not in sess.stayed|sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.",view=BlackjackPlayView(target_uid=u))

class AceChoiceView(View):
    def __init__(self,target_uid,card_index):
        super().__init__(timeout=None)
        self.target_uid=target_uid; self.card_index=card_index
        self.add_item(AceBtn(1)); self.add_item(AceBtn(11))

class AceBtn(Button):
    def __init__(self,val): super().__init__(label=f"A={val}",style=discord.ButtonStyle.primary if val==1 else discord.ButtonStyle.success); self.val=val
    async def callback(self, inter):
        cid,uid,uname=str(inter.channel.id),str(inter.user.id),inter.user.display_name
        if cid not in blackjack_sessions: await inter.response.send_message("세션 없음",ephemeral=True);return
        sess=blackjack_sessions[cid]
        if uid!=self.view.target_uid: await inter.response.send_message("⛔ 본인만 조작",ephemeral=True);return
        sess.ace_values[uid][self.view.card_index]=self.val; sc=sess.score(uid)
        await inter.channel.send(f"{uname} A={self.val} 선택 → {' '.join(sess.players[uid])} (합계 {sc})")
        if sc==21:
            await inter.channel.send(f"🎉 {uname} 블랙잭! (합계 21)"); sess.stay(uid); sess.actions[uid]=True; await settle_and_end(inter,"bj",sess);return
        if sc>21:
            sess.busted.add(uid); await inter.channel.send(f"💥 {uname} 버스트! (합계 {sc})")
        sess.actions[uid]=True
        if sess.everyone_acted():
            if sess.is_finished(): await settle_and_end(inter,"bj",sess)
            else:
                sess.reset_actions()
                for u in sess.players:
                    if u not in sess.stayed|sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.",view=BlackjackPlayView(target_uid=u))

# ─────────────────────────────────────────────
# ♥ 블라인드 블랙잭 플레이 버튼
# ─────────────────────────────────────────────
class BlindPlayView(View):
    def __init__(self,target_uid):
        super().__init__(timeout=None)
        self.target_uid=target_uid
        self.add_item(BlindHitButton())
        self.add_item(BlindStayButton())

class BlindHitButton(Button):
    def __init__(self): super().__init__(label="히트(비공개)",style=discord.ButtonStyle.success)
    async def callback(self, inter):
        cid,uid,uname=str(inter.channel.id),str(inter.user.id),inter.user.display_name
        if cid not in blind_sessions: await inter.response.send_message("세션 없음",ephemeral=True);return
        sess=blind_sessions[cid]
        if uid!=self.view.target_uid: await inter.response.send_message("⛔ 본인만 조작",ephemeral=True);return
        card=sess.hit(uid); sc=sess.score(uid)
        if sc==21:
            await inter.channel.send(f"🎉 {uname} 블랙잭! (합계 21, 비공개)")
            sess.stay(uid); sess.actions[uid]=True; await settle_and_end(inter,"blind",sess);return
        if sc>21:
            sess.busted.add(uid); await inter.channel.send(f"💥 {uname} 버스트! (합계 {sc}, 비공개)")
        else:
            await inter.channel.send(f"{uname} 히트 완료 (합계 {sc}, 비공개)")
        sess.actions[uid]=True
        if sess.everyone_acted():
            if sess.is_finished(): await settle_and_end(inter,"blind",sess)
            else:
                sess.reset_actions()
                for u in sess.players:
                    if u not in sess.stayed|sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.",view=BlindPlayView(target_uid=u))

class BlindStayButton(Button):
    def __init__(self): super().__init__(label="스테이",style=discord.ButtonStyle.danger)
    async def callback(self, inter):
        cid,uid,uname=str(inter.channel.id),str(inter.user.id),inter.user.display_name
        if cid not in blind_sessions: await inter.response.send_message("세션 없음",ephemeral=True);return
        sess=blind_sessions[cid]
        if uid!=self.view.target_uid: await inter.response.send_message("⛔ 본인만 조작",ephemeral=True);return
        sess.stay(uid); sc=sess.score(uid)
        await inter.channel.send(f"{uname} 스테이 (합계 {sc}, 비공개)")
        if sess.everyone_acted():
            if sess.is_finished(): await settle_and_end(inter,"blind",sess)
            else:
                sess.reset_actions()
                for u in sess.players:
                    if u not in sess.stayed|sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.",view=BlindPlayView(target_uid=u))

# ─────────────────────────────────────────────
# 💰 정산
# ─────────────────────────────────────────────
async def settle_and_end(inter,mode,sess):
    ch=inter.channel
    scores={u:sess.score(u) for u in sess.players}
    alive={u:s for u,s in scores.items() if s<=21}
    lines=[]
    for u in sess.players:
        m=ch.guild.get_member(int(u)); n=m.display_name if m else u; s=scores[u]
        if mode=="bj":
            cards=" ".join(sess.players[u])
            lines.append(f"**{n}** → {cards} ({'버스트' if s>21 else s})")
        else:
            cards = " ".join(sess.hidden_info[u]["cards"])
            score = sess.hidden_info[u]["score"]
            lines.append(f"**{n}** → {cards} (합계 {score}{' 버스트' if score>21 else ''})")
    if not alive:
        await ch.send("모두 버스트! 전원 패배.")
        for u,b in sess.bets.items(): add_balance(u,ch.guild.get_member(int(u)).display_name,-b)
    else:
        max_s=max(alive.values()); winners=[u for u,s in alive.items() if s==max_s]
        for u in sess.players:
            m=ch.guild.get_member(int(u)); n=m.display_name if m else u; b=sess.bets[u]
            if u in winners: add_balance(u,n,b); await ch.send(f"🏆 {n} 승리! (+{b})")
            else: add_balance(u,n,-b); await ch.send(f"❌ {n} 패배 (-{b})")
    await ch.send("🃏 결과\n"+"\n".join(lines))
    shuffle_decks(sess.cid)
    if mode=="bj": del blackjack_sessions[sess.cid]
    else: del blind_sessions[sess.cid]
    await ch.send("🎮 게임 종료! `!세팅`으로 새 게임을 시작하세요.")

# ─────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
