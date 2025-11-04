# 🔐 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random, os, json, sys, math
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ────────────────────────────────────────────────────────────────
# 📊 Google Sheets 인증 (환경변수 필요)
# ────────────────────────────────────────────────────────────────
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

# ────────────────────────────────────────────────────────────────
# 📦 시트 유틸
# ────────────────────────────────────────────────────────────────
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
    if row:
        return row
    sh.append_row([user_id, user_name, 100, now_kst_str()])
    return sh.row_count

def get_balance(user_id: str, user_name: str) -> int:
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        return 100
    raw = sh.cell(row, 3).value
    return int(raw or 0)

def add_balance(user_id: str, user_name: str, delta: int) -> int:
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        ensure_user_row(user_id, user_name)
        row = _find_row_by_id(sh, user_id)
    cur = int(sh.cell(row, 3).value or 0)
    new_val = max(cur + delta, 0)
    sh.update_acell(f"C{row}", new_val)
    sh.update_acell(f"D{row}", now_kst_str())
    return new_val

# ────────────────────────────────────────────────────────────────
# ♣ 카드 덱
# ────────────────────────────────────────────────────────────────
channel_decks = {}
suits = ['♠','♥','♦','♣']
ranks = ['A'] + [str(n) for n in range(2,11)] + ['J','Q','K']
full_deck = [f"{s}{r}" for s in suits for r in ranks]

def shuffle_decks(cid: str):
    channel_decks[cid] = {
        "blackjack": random.sample(full_deck, len(full_deck)),
        "blind_blackjack": random.sample(full_deck, len(full_deck))
    }

def ensure_channel_setup(cid: str):
    if cid not in channel_decks:
        shuffle_decks(cid)

# ────────────────────────────────────────────────────────────────
# 🔗 세션 저장소
# ────────────────────────────────────────────────────────────────
blackjack_sessions = {}
blind_blackjack_sessions = {}

# ────────────────────────────────────────────────────────────────
# ⚙️ 기본 이벤트
# ────────────────────────────────────────────────────────────────

@bot.command(name="세팅", help="게임 메뉴를 표시합니다.")
async def 세팅(ctx):
    ensure_channel_setup(str(ctx.channel.id))
    await ctx.send("게임을 선택하세요.", view=GameMenu())

@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f"✅ Logged in as {bot.user}")

# ────────────────────────────────────────────────────────────────
# 🎮 메인 메뉴
# ────────────────────────────────────────────────────────────────
class GameMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MenuButton("블랙잭", "blackjack", discord.ButtonStyle.danger, 0))
        self.add_item(MenuButton("블라인드 블랙잭", "blindbj", discord.ButtonStyle.danger, 0))
        self.add_item(MenuButton("가위바위보", "rps", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("홀짝", "odd_even", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("야바위", "shell", discord.ButtonStyle.primary, 1))
        self.add_item(MenuButton("슬롯머신", "slot", discord.ButtonStyle.success, 2))
        self.add_item(MenuButton("다이스", "dice", discord.ButtonStyle.success, 2))
        # 유저등록 (회색, 맨 밑)
        self.add_item(MenuButton("유저 등록", "user_reg", discord.ButtonStyle.secondary, 4))

class MenuButton(discord.ui.Button):
    def __init__(self, label, custom_id, style, row):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)
    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        ensure_channel_setup(cid)

        if self.custom_id == "user_reg":
            await register_user_via_button(inter)
            return

        if self.custom_id == "blackjack":
            if cid in blackjack_sessions or cid in blind_blackjack_sessions:
                await inter.response.send_message("⚠️ 이미 진행 중인 세션이 있습니다.", ephemeral=True)
                return
            await inter.response.send_message("🃏 **블랙잭** — 인원수를 선택하세요.", view=PlayerCountSelectView("bj"))
            return

        if self.custom_id == "blindbj":
            if cid in blackjack_sessions or cid in blind_blackjack_sessions:
                await inter.response.send_message("⚠️ 이미 진행 중인 세션이 있습니다.", ephemeral=True)
                return
            await inter.response.send_message("🃏 **블라인드 블랙잭** — 인원수를 선택하세요.", view=PlayerCountSelectView("blind"))
            return

async def register_user_via_button(inter: discord.Interaction):
    uid = str(inter.user.id)
    uname = inter.user.display_name
    if _find_row_by_id(ws("소지금"), uid):
        add_balance(uid, uname, 0)
        await inter.response.send_message(f"✅ 이미 등록됨 — 수정일 갱신\n{uname} ({uid})")
    else:
        ensure_user_row(uid, uname)
        await inter.response.send_message(f"🎉 유저 등록 완료 — {uname} ({uid}) / 소지금 100")

# ────────────────────────────────────────────────────────────────
# 👥 인원 선택
# ────────────────────────────────────────────────────────────────
class PlayerCountSelectView(View):
    def __init__(self, mode):
        super().__init__(timeout=None)
        self.mode = mode
        for n in range(2,5):
            self.add_item(PlayerCountButton(n, mode))

class PlayerCountButton(Button):
    def __init__(self, count, mode):
        super().__init__(label=f"{count}명", style=discord.ButtonStyle.primary)
        self.count = count; self.mode = mode
    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        deck = channel_decks[cid]["blackjack" if self.mode=="bj" else "blind_blackjack"]
        if self.mode == "bj":
            blackjack_sessions[cid] = BlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블랙잭({self.count}명) 세션 생성! `!참가 금액`으로 참가하세요.")
        else:
            blind_blackjack_sessions[cid] = BlindBlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블라인드 블랙잭({self.count}명) 세션 생성! `!참가 금액`으로 참가하세요.")

# ────────────────────────────────────────────────────────────────
# 🎮 블랙잭 세션
# ────────────────────────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, cid, deck_ref, max_players):
        self.cid = cid; self.deck = deck_ref; self.max_players = max_players
        self.players, self.ace_values, self.actions = {}, {}, {}
        self.stayed, self.busted, self.bets = set(), set(), {}
        self.started = False

    def deal_initial(self, uid):
        self.players[uid] = [self.deck.pop(), self.deck.pop()]
        self.ace_values[uid] = {}
        self.actions[uid] = False

    def score(self, uid):
        total = 0
        for i,c in enumerate(self.players[uid]):
            r = c[1:]
            total += 10 if r in ["J","Q","K"] else (self.ace_values.get(uid,{}).get(i,11) if r=="A" else int(r))
        return total

    def hit(self, uid):
        card = self.deck.pop(); self.players[uid].append(card); self.actions[uid] = True; return card

    def stay(self, uid): self.stayed.add(uid); self.actions[uid] = True
    def everyone_joined(self): return len(self.bets) == self.max_players
    def everyone_acted(self): return all(self.actions.get(u,False) or u in self.busted for u in self.players)
    def reset_actions(self): [self.actions.update({u:False}) for u in self.players if u not in self.stayed and u not in self.busted]
    def is_finished(self): return all(u in self.stayed or self.score(u)>21 for u in self.players)

# ────────────────────────────────────────────────────────────────
# 🎮 블라인드 블랙잭
# ────────────────────────────────────────────────────────────────
class BlindBlackjackSession(BlackjackSession):
    def score(self, uid):
        total = 0
        for c in self.players[uid]:
            r = c[1:]
            total += 1 if r=="A" else (10 if r in ["J","Q","K"] else int(r))
        return total

# ────────────────────────────────────────────────────────────────
# 🎮 참가 명령어
# ────────────────────────────────────────────────────────────────

@bot.command(name="참가")
async def 참가(ctx, 금액: str = None):
    cid, uid, uname = str(ctx.channel.id), str(ctx.author.id), ctx.author.display_name
    if cid in blackjack_sessions:
        sess, mode = blackjack_sessions[cid], "bj"
    elif cid in blind_blackjack_sessions:
        sess, mode = blind_blackjack_sessions[cid], "blind"
    else:
        await ctx.send("❌ 현재 세션이 없습니다. `!세팅`으로 시작하세요."); return

    if sess.started:
        await ctx.send("⚠️ 이미 게임이 시작되었습니다."); return

    if not 금액 or not 금액.isdigit() or int(금액)<=0:
        await ctx.send("💰 베팅 금액을 입력하세요. 예) `!참가 20`"); return
    bet = int(금액)

    ensure_user_row(uid, uname)
    bal = get_balance(uid, uname)
    if bet > bal:
        await ctx.send(f"❌ 소지금({bal})보다 많습니다."); return

    sess.bets[uid] = bet
    await ctx.send(f"✅ {uname} 참가 — 베팅 {bet}")

    # 전원 참가 완료 시
    if sess.everyone_joined():
        sess.started = True
        await ctx.send(f"✅ 참가자({sess.max_players}명) 전원 참가 완료!\n🃏 첫 카드 분배를 시작합니다...")
    
        # 카드 분배
        for u in sess.bets.keys():
            sess.deal_initial(u)
    
        # 각 플레이어 카드 안내
        for u in sess.players.keys():
            member = ctx.guild.get_member(int(u))
            name = member.display_name if member else f"UID:{u}"
            cards = ' '.join(sess.players[u])
            score = sess.score(u)
            await ctx.send(f"**{name}** 님의 첫 패: {cards} (합계 {score})")
    
        # 블라인드 BJ는 전원 버스트 시 재배분
        if mode == "blind" and hasattr(sess, "initial_all_bust") and sess.initial_all_bust():
            sess.redeal_all()
            await ctx.send("⚠️ 최초 분배가 전원 버스트여서 재배분합니다.")
    
        # 참가자 안내
        names = [ctx.guild.get_member(int(u)).display_name for u in sess.bets]
        await ctx.send(f"🎮 게임 시작!\n참가자: {', '.join(names)}")
    
        # 첫 라운드 버튼 생성
        for u in sess.players.keys():
            if mode == "bj":
                await ctx.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))
            else:
                await ctx.send(f"<@{u}> 님 차례입니다.", view=BlindPlayView(target_uid=u))


# ────────────────────────────────────────────────────────────────
# 🎮 블랙잭 플레이 (히트/스테이)
# ────────────────────────────────────────────────────────────────
class BlackjackPlayView(View):
    def __init__(self, target_uid):
        super().__init__(timeout=None)
        self.target_uid = target_uid
        self.add_item(BJHitButton())
        self.add_item(BJStayButton())

class BJHitButton(Button):
    def __init__(self):
        super().__init__(label="히트", style=discord.ButtonStyle.success)

    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blackjack_sessions:
            await inter.response.send_message("세션이 없습니다.", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작할 수 있습니다.", ephemeral=True); return

        card = sess.hit(uid)
        sc = sess.score(uid)

        if card[1:] == "A":
            idx = len(sess.players[uid]) - 1
            await inter.channel.send(f"{uname}님, 새 카드 {card} — A값을 선택하세요.",
                                     view=AceChoiceView(target_uid=uid, card_index=idx))
            return

        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 {uname} 버스트! 합계 {sc}")
        else:
            await inter.channel.send(f"{uname}: {' '.join(sess.players[uid])} (합계 {sc})")

        sess.actions[uid] = True
        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="bj", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))

class BJStayButton(Button):
    def __init__(self):
        super().__init__(label="스테이", style=discord.ButtonStyle.danger)

    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blackjack_sessions:
            await inter.response.send_message("세션이 없습니다.", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작할 수 있습니다.", ephemeral=True); return

        sess.stay(uid)
        sc = sess.score(uid)
        await inter.channel.send(f"{uname} 스테이 (합계 {sc})")

        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="bj", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))

# ────────────────────────────────────────────────────────────────
# 🅰️ 에이스 선택
# ────────────────────────────────────────────────────────────────
class AceChoiceView(View):
    def __init__(self, target_uid, card_index):
        super().__init__(timeout=None)
        self.target_uid = target_uid
        self.card_index = card_index
        self.add_item(AceBtn(1))
        self.add_item(AceBtn(11))

class AceBtn(Button):
    def __init__(self, val):
        super().__init__(label=f"A={val}", style=discord.ButtonStyle.primary if val==1 else discord.ButtonStyle.success)
        self.val = val

    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blackjack_sessions:
            await inter.response.send_message("세션이 없습니다.", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작할 수 있습니다.", ephemeral=True); return

        sess.ace_values[uid][self.view.card_index] = self.val
        sc = sess.score(uid)
        await inter.channel.send(f"{uname} — A={self.val} 선택 → {' '.join(sess.players[uid])} (합계 {sc})")

        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 {uname} 버스트!")

        sess.actions[uid] = True
        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="bj", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))

# ────────────────────────────────────────────────────────────────
# 🎮 블라인드 블랙잭 플레이
# ────────────────────────────────────────────────────────────────
class BlindPlayView(View):
    def __init__(self, target_uid):
        super().__init__(timeout=None)
        self.target_uid = target_uid
        self.add_item(BlindHitBtn())
        self.add_item(BlindStayBtn())

class BlindHitBtn(Button):
    def __init__(self):
        super().__init__(label="히트(비공개)", style=discord.ButtonStyle.success)
    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blind_blackjack_sessions:
            await inter.response.send_message("세션이 없습니다.", ephemeral=True); return
        sess = blind_blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작할 수 있습니다.", ephemeral=True); return

        card = sess.hit(uid)
        sc = sess.score(uid)
        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 {uname} 버스트 (합계 {sc})")
        else:
            await inter.channel.send(f"{uname} 히트 완료 (합계 {sc} 비공개)")

        sess.actions[uid] = True
        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="blind", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlindPlayView(target_uid=u))

class BlindStayBtn(Button):
    def __init__(self):
        super().__init__(label="스테이", style=discord.ButtonStyle.danger)
    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blind_blackjack_sessions:
            await inter.response.send_message("세션이 없습니다.", ephemeral=True); return
        sess = blind_blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작할 수 있습니다.", ephemeral=True); return

        sess.stay(uid)
        sc = sess.score(uid)
        await inter.channel.send(f"{uname} 스테이 (합계 {sc} 비공개)")

        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="blind", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlindPlayView(target_uid=u))

# ────────────────────────────────────────────────────────────────
# 💰 정산 및 종료
# ────────────────────────────────────────────────────────────────
async def settle_and_end(inter: discord.Interaction, mode: str, sess):
    ch = inter.channel

    get_score = sess.score
    players = sess.players
    scores = {u: get_score(u) for u in players}
    alive = {u: s for u, s in scores.items() if s <= 21}

    lines = []
    for u in players:
        member = ch.guild.get_member(int(u))
        name = member.display_name if member else f"UID:{u}"
        s = scores[u]
        state = "버스트 ❌" if s > 21 else f"합계 {s}"
        if mode == "bj":
            cards = ' '.join(players[u])
            lines.append(f"**{name}** → {cards} ({state}) / 베팅 {sess.bets[u]}")
        else:
            lines.append(f"**{name}** → ({state}, 카드 비공개) / 베팅 {sess.bets[u]}")

    await ch.send("🃏 결과 발표\n" + "\n".join(lines))

    if not alive:
        await ch.send("💥 전원 버스트! 전원 베팅액 차감")
        for u, bet in sess.bets.items():
            member = ch.guild.get_member(int(u))
            name = member.display_name if member else u
            newbal = add_balance(u, name, -bet)
            await ch.send(f"🔻 {name} -{bet} → {newbal}")
    else:
        max_s = max(alive.values())
        winners = [u for u,s in alive.items() if s == max_s]
        losers = [u for u in players.keys() if u not in winners]

        pot = sum(sess.bets[u] for u in losers)
        share = pot // len(winners)
        rem = pot % len(winners)

        for u in losers:
            member = ch.guild.get_member(int(u))
            name = member.display_name if member else u
            bet = sess.bets[u]
            newbal = add_balance(u, name, -bet)
            await ch.send(f"🔻 {name} -{bet} → {newbal}")

        for idx, u in enumerate(winners):
            member = ch.guild.get_member(int(u))
            name = member.display_name if member else u
            bet = sess.bets[u]
            gain = bet + share + (1 if idx < rem else 0)
            newbal = add_balance(u, name, gain)
            await ch.send(f"🏆 {name} +{gain} → {newbal}")

        if len(winners) == 1:
            wname = ch.guild.get_member(int(winners[0])).display_name
            await ch.send(f"🎉 승자: **{wname}** (합계 {max_s})")
        else:
            wnames = [ch.guild.get_member(int(u)).display_name for u in winners]
            await ch.send(f"🤝 공동 승리: {', '.join(wnames)} (합계 {max_s})")

    shuffle_decks(sess.cid)
    if mode == "bj": del blackjack_sessions[sess.cid]
    else: del blind_blackjack_sessions[sess.cid]
    await ch.send("🎮 **게임 종료!** 새로운 게임은 `!세팅`으로 시작하세요.")


bot.run(DISCORD_TOKEN)
