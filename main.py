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

missing = [k for k,v in {
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "GOOGLE_CREDS": GOOGLE_CREDS,
    "SHEET_KEY": SHEET_KEY
}.items() if not v]
if missing:
    print("누락된 환경변수:", ", ".join(missing))
    sys.exit(1)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
try:
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gclient = gspread.authorize(creds)
except Exception as e:
    print("구글 인증 실패:", e)
    sys.exit(1)

def ws(title: str):
    return gclient.open_by_key(SHEET_KEY).worksheet(title)

# ────────────────────────────────────────────────────────────────
# 🧰 유틸/시트 함수
# ────────────────────────────────────────────────────────────────
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

def _find_row_by_id(sh, user_id: str) -> int | None:
    col_a = sh.col_values(1)
    for idx, v in enumerate(col_a, start=1):
        if (v or "").strip() == user_id:
            return idx
    return None

def ensure_user_row(user_id: str, user_name: str) -> int:
    """소지금 시트에 유저가 없으면 A=id, B=이름, C=100, D=최근수정일 로 생성하고 행번호 반환"""
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if row:
        return row
    sh.append_row([user_id, user_name, 100, now_kst_str()])
    return sh.row_count  # append 후 마지막행이 됨(구글 API가 자동 확장)

def get_balance(user_id: str, user_name: str) -> int:
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        return 100  # 아직 없으면 논리상 100으로 간주(실제 생성은 update/set 시점에)
    raw = sh.cell(row, 3).value
    return int(raw or 0)

def set_balance(user_id: str, user_name: str, value: int) -> int:
    sh = ws("소지금")
    row = _find_row_by_id(sh, user_id)
    if not row:
        ensure_user_row(user_id, user_name)
        sh = ws("소지금")
        row = _find_row_by_id(sh, user_id)
    value = max(int(value), 0)
    sh.update_acell(f"C{row}", value)
    sh.update_acell(f"D{row}", now_kst_str())
    return value

def add_balance(user_id: str, user_name: str, delta: int) -> int:
    cur = get_balance(user_id, user_name)
    return set_balance(user_id, user_name, cur + delta)

# ────────────────────────────────────────────────────────────────
# ♣ 카드 덱 관리 (채널별)
# ────────────────────────────────────────────────────────────────
channel_decks = {}
suits = ['♠', '♥', '♦', '♣']
ranks = ['A'] + [str(n) for n in range(2, 11)] + ['J', 'Q', 'K']
full_deck = [f"{s}{r}" for s in suits for r in ranks]

def shuffle_decks(channel_id: str):
    channel_decks[channel_id] = {
        "blackjack": random.sample(full_deck, len(full_deck)),
        "blind_blackjack": random.sample(full_deck, len(full_deck))
    }

def ensure_channel_setup(channel_id: str):
    if channel_id not in channel_decks:
        shuffle_decks(channel_id)

# ────────────────────────────────────────────────────────────────
# 🔗 세션 저장소
# ────────────────────────────────────────────────────────────────
blackjack_sessions = {}         # {channel_id: BlackjackSession}
blind_blackjack_sessions = {}   # {channel_id: BlindBlackjackSession}

# ────────────────────────────────────────────────────────────────
# ⚙️ 기본 이벤트/명령
# ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f"✅ Logged in as {bot.user}")

@bot.command(name="세팅")
async def 세팅(ctx):
    ensure_channel_setup(str(ctx.channel.id))
    await ctx.send("게임을 선택하세요.", view=GameMenu())

@bot.command(name="유저", help="현재 사용자를 '소지금' 시트에 등록/갱신합니다. (기본 100 포인트)")
async def 유저_cmd(ctx):
    try:
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        row = _find_row_by_id(ws("소지금"), user_id)
        if row:
            set_balance(user_id, user_name, get_balance(user_id, user_name))  # 수정일만 갱신
            await ctx.send(f"✅ 이미 등록된 유저입니다. 수정일을 갱신했습니다.\n{user_name} ({user_id})")
        else:
            ensure_user_row(user_id, user_name)
            await ctx.send(f"🎉 유저 등록 완료 — {user_name} ({user_id}) / 소지금 100")
    except Exception as e:
        await ctx.send(f"⚠️ 등록 실패: {e}")

# ────────────────────────────────────────────────────────────────
# 🎮 메인 메뉴 + 미니게임
# ────────────────────────────────────────────────────────────────
class GameMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        # 카드류
        self.add_item(MenuButton("블랙잭", "blackjack", discord.ButtonStyle.danger, 0))
        self.add_item(MenuButton("블라인드 블랙잭", "blindbj", discord.ButtonStyle.danger, 0))
        # 유저 등록
        self.add_item(MenuButton("유저 등록", "user_reg", discord.ButtonStyle.success, 1))
        # 라이트 게임
        self.add_item(MenuButton("가위바위보", "rps", discord.ButtonStyle.primary, 2))
        self.add_item(MenuButton("홀짝", "odd_even", discord.ButtonStyle.primary, 2))
        self.add_item(MenuButton("야바위", "shell", discord.ButtonStyle.primary, 2))
        # 슬롯/다이스
        self.add_item(MenuButton("슬롯머신", "slot", discord.ButtonStyle.success, 3))
        self.add_item(MenuButton("다이스", "dice", discord.ButtonStyle.success, 3))

class MenuButton(discord.ui.Button):
    def __init__(self, label, custom_id, style, row):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        ensure_channel_setup(cid)

        # 유저 등록 버튼
        if self.custom_id == "user_reg":
            await register_user_via_button(inter)
            return

        # 블랙잭 시작
        if self.custom_id == "blackjack":
            if cid in blackjack_sessions or cid in blind_blackjack_sessions:
                await inter.response.send_message("⚠️ 이미 진행 중인 게임이 있습니다. 먼저 종료하세요.", ephemeral=True)
                return
            await inter.response.send_message("🃏 **블랙잭** — 인원수를 선택하세요.", view=PlayerCountSelectView(mode="bj"))
            return

        # 블라인드 블랙잭 시작
        if self.custom_id == "blindbj":
            if cid in blackjack_sessions or cid in blind_blackjack_sessions:
                await inter.response.send_message("⚠️ 이미 진행 중인 게임이 있습니다. 먼저 종료하세요.", ephemeral=True)
                return
            await inter.response.send_message("🃏 **블라인드 블랙잭** — 인원수를 선택하세요.", view=PlayerCountSelectView(mode="blind"))
            return

        # 가위바위보
        if self.custom_id == "rps":
            await inter.response.send_message(f"✂️ 결과: {random.choice(['가위','바위','보'])}\n{now_kst_str()}")
            return

        # 홀짝
        if self.custom_id == "odd_even":
            arr = ["홀" if random.randint(1,6)%2 else "짝" for _ in range(3)]
            await inter.response.send_message(f"⚪ 홀짝: {' '.join(arr)}\n{now_kst_str()}")
            return

        # 야바위
        if self.custom_id == "shell":
            await inter.response.send_message(f"🎲 야바위: {random.choice(['OXX','XOX','XXO'])}\n{now_kst_str()}")
            return

        # 슬롯머신
        if self.custom_id == "slot":
            symbols = ['❤️','💔','💖','💝','🔴','🔥','🦋','💥']
            reels = [random.choice(symbols) for _ in range(3)]
            if reels.count(reels[0]) == 3:
                guide = "💥 잭팟! (x5)"
            elif len(set(reels)) == 2:
                guide = "💎 더블! (x2)"
            else:
                guide = "❌ 꽝!"
            await inter.response.send_message(f"{' '.join(reels)}\n{guide}\n{now_kst_str()}")
            return

        # 다이스
        if self.custom_id == "dice":
            await inter.response.send_message(f"{inter.user.mention} 주사위를 선택하세요.", view=DiceView(owner_id=inter.user.id))
            return

async def register_user_via_button(inter: discord.Interaction):
    try:
        user_id = str(inter.user.id)
        user_name = inter.user.display_name
        if _find_row_by_id(ws("소지금"), user_id):
            set_balance(user_id, user_name, get_balance(user_id, user_name))  # 수정일 갱신
            await inter.response.send_message(f"✅ 이미 등록됨 — 수정일 갱신\n{user_name} ({user_id})")
        else:
            ensure_user_row(user_id, user_name)
            await inter.response.send_message(f"🎉 유저 등록 완료 — {user_name} ({user_id}) / 소지금 100")
    except Exception as e:
        await inter.response.send_message(f"⚠️ 등록 실패: {e}")

# 🎲 다이스
class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id
    async def callback(self, inter: discord.Interaction):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("⛔ 당신의 다이스가 아닙니다.", ephemeral=True); return
        await inter.response.send_message(f"🎲 1d{self.sides}: {random.randint(1, self.sides)}\n{now_kst_str()}")

class DiceView(View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.add_item(DiceButton(6, discord.ButtonStyle.danger, owner_id))
        self.add_item(DiceButton(10, discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))

# 👥 인원 선택
class PlayerCountSelectView(View):
    def __init__(self, mode: str):
        super().__init__(timeout=None)
        self.mode = mode  # "bj" | "blind"
        for n in range(2, 4+1):
            self.add_item(PlayerCountButton(n, mode))

class PlayerCountButton(Button):
    def __init__(self, count: int, mode: str):
        super().__init__(label=f"{count}명", style=discord.ButtonStyle.primary)
        self.count = count
        self.mode = mode
    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        deck = channel_decks[cid]["blackjack" if self.mode=="bj" else "blind_blackjack"]
        if self.mode == "bj":
            blackjack_sessions[cid] = BlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블랙잭({self.count}명) 세션 생성! `!참가 베팅금액` 으로 참가하세요. (예: `!참가 20`)")
        else:
            blind_blackjack_sessions[cid] = BlindBlackjackSession(cid, deck, self.count)
            await inter.response.send_message(f"🃏 블라인드 블랙잭({self.count}명) 세션 생성! `!참가 베팅금액` 으로 참가하세요. (예: `!참가 20`)")

# ────────────────────────────────────────────────────────────────
# 🃏 블랙잭(표준) 세션
# ────────────────────────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, cid, deck_ref, max_players):
        self.cid = cid
        self.deck = deck_ref
        self.max_players = max_players
        self.players = {}         # uid: [cards...]
        self.ace_values = {}      # uid: {card_index: 1|11}
        self.actions = {}         # uid: acted this round?
        self.stayed = set()
        self.busted = set()
        self.bets = {}            # uid: bet amount
        self.started = False

    def deal_initial(self, uid):
        if uid not in self.players:
            self.players[uid] = [self.deck.pop(), self.deck.pop()]
            self.ace_values[uid] = {}
            self.actions[uid] = False
        return self.players[uid]

    def score(self, uid):
        total = 0
        for i, c in enumerate(self.players[uid]):
            r = c[1:]
            if r in ["J","Q","K"]:
                total += 10
            elif r == "A":
                total += self.ace_values.get(uid, {}).get(i, 11)
            else:
                total += int(r)
        return total

    def hit(self, uid):
        card = self.deck.pop()
        self.players[uid].append(card)
        self.actions[uid] = True
        return card

    def stay(self, uid):
        self.stayed.add(uid)
        self.actions[uid] = True

    def everyone_joined(self):
        return len(self.players) == self.max_players and len(self.bets) == self.max_players

    def everyone_acted(self):
        if not self.started: return False
        return all(self.actions.get(u, False) or u in self.busted for u in self.players)

    def reset_actions(self):
        for u in self.players:
            if u not in self.stayed and u not in self.busted:
                self.actions[u] = False

    def is_finished(self):
        if not self.started: return False
        return all(u in self.stayed or self.score(u) > 21 for u in self.players)

# ────────────────────────────────────────────────────────────────
# 🃏 블라인드 블랙잭 세션 (카드 비공개, A=1 고정)
# ────────────────────────────────────────────────────────────────
class BlindBlackjackSession:
    def __init__(self, cid, deck_ref, max_players):
        self.cid = cid
        self.deck = deck_ref
        self.max_players = max_players
        self.players = {}     # uid: [cards...]
        self.actions = {}     # uid: acted?
        self.stayed = set()
        self.busted = set()
        self.bets = {}        # uid: bet amount
        self.started = False

    def _card_value(self, r):
        if r in ["J","Q","K"]: return 10
        if r == "A": return 1   # 고정
        return int(r)

    def score(self, uid):
        return sum(self._card_value(c[1:]) for c in self.players[uid])

    def deal_initial(self, uid):
        if uid not in self.players:
            self.players[uid] = [self.deck.pop(), self.deck.pop()]
            self.actions[uid] = False
        return self.players[uid]

    def initial_all_bust(self):
        # 모든 참가자의 최초 2장 합이 22 이상이면(=둘 다 10/J/Q/K 등) 재배분
        if len(self.players) < self.max_players: return False
        return all(self.score(u) > 21 for u in self.players)

    def redeal_all(self):
        # 모두 버스트였을 때 다시 2장씩 분배
        for u in list(self.players.keys()):
            self.players[u] = [self.deck.pop(), self.deck.pop()]
            self.actions[u] = False
            if u in self.busted: self.busted.remove(u)
            if u in self.stayed: self.stayed.remove(u)

    def hit(self, uid):
        card = self.deck.pop()
        self.players[uid].append(card)
        self.actions[uid] = True
        return card

    def stay(self, uid):
        self.stayed.add(uid)
        self.actions[uid] = True

    def everyone_joined(self):
        return len(self.players) == self.max_players and len(self.bets) == self.max_players

    def everyone_acted(self):
        if not self.started: return False
        return all(self.actions.get(u, False) or u in self.busted for u in self.players)

    def reset_actions(self):
        for u in self.players:
            if u not in self.stayed and u not in self.busted:
                self.actions[u] = False

    def is_finished(self):
        if not self.started: return False
        return all(u in self.stayed or self.score(u) > 21 for u in self.players)

# ────────────────────────────────────────────────────────────────
# 🎮 참가 (블랙잭/블라인드 공용) — !참가 베팅금액
# ────────────────────────────────────────────────────────────────

@bot.command(name="참가", help="현재 세션에 베팅하고 참가합니다. 예) !참가 20")
async def 참가(ctx, 금액: str = None):
    cid = str(ctx.channel.id)
    uid = str(ctx.author.id)
    uname = ctx.author.display_name

    sess = None
    mode = None
    if cid in blackjack_sessions:
        sess = blackjack_sessions[cid]; mode = "bj"
    elif cid in blind_blackjack_sessions:
        sess = blind_blackjack_sessions[cid]; mode = "blind"
    else:
        await ctx.send("❌ 현재 진행 중인 세션이 없습니다. `!세팅`으로 시작하세요.")
        return

    if sess.started:
        await ctx.send("⚠️ 이미 게임이 시작되었습니다.")
        return

    if 금액 is None or not 금액.isdigit() or int(금액) <= 0:
        await ctx.send("베팅 금액을 양의 정수로 입력하세요. 예) `!참가 20`")
        return
    bet = int(금액)

    ensure_user_row(uid, uname)
    bal = get_balance(uid, uname)
    if bet > bal:
        await ctx.send(f"❌ 베팅 금액이 소지금({bal})을 초과합니다.")
        return

    sess.bets[uid] = bet
    await ctx.send(f"**{uname}** 참가 완료 — 베팅 {bet}")

    # 전원 참가 완료 시 시작
    if sess.everyone_joined():
        sess.started = True
        await ctx.send(f"✅ 참가자({sess.max_players}명) 전원 참가 완료!\n🃏 카드 분배를 시작합니다...")

        # 카드 분배
        for u in sess.bets.keys():
            sess.deal_initial(u)

        # 블라인드 BJ는 버스트 검사
        if mode == "blind" and sess.initial_all_bust():
            sess.redeal_all()
            await ctx.send("⚠️ 최초 분배가 전원 버스트여서 재배분합니다.")

        # 참가자 안내
        names = [ctx.guild.get_member(int(u)).display_name for u in sess.players]
        await ctx.send(f"🎮 게임 시작!\n참가자: {', '.join(names)}")

        # 첫 라운드 버튼
        for u in sess.players.keys():
            if mode == "bj":
                await ctx.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))
            else:
                await ct

# ────────────────────────────────────────────────────────────────
# 🎮 블랙잭 플레이 뷰 (개인 전용 버튼)
# ────────────────────────────────────────────────────────────────
class BlackjackPlayView(View):
    def __init__(self, target_uid: str):
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
            await inter.response.send_message("세션 없음", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작 가능", ephemeral=True); return
        card = sess.hit(uid)
        idx = len(sess.players[uid]) - 1
        sc = sess.score(uid)

        # 에이스 선택 필요?
        if card[1:] == "A":
            await inter.channel.send(f"**{uname}** 새 카드 {card} — A값을 선택하세요.", view=AceChoiceView(target_uid=uid, card_index=idx))
            return

        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트** — {' '.join(sess.players[uid])} (합계 {sc})")
        else:
            await inter.channel.send(f"**{uname}** → {' '.join(sess.players[uid])} (합계 {sc})")

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
            await inter.response.send_message("세션 없음", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작 가능", ephemeral=True); return
        sess.stay(uid)
        sc = sess.score(uid)
        await inter.channel.send(f"**{uname}** 스테이 (합계 {sc})")

        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="bj", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))

# 🅰️ 에이스 값 선택
class AceChoiceView(View):
    def __init__(self, target_uid: str, card_index: int):
        super().__init__(timeout=None)
        self.target_uid = target_uid
        self.card_index = card_index
        self.add_item(AceBtn(1))
        self.add_item(AceBtn(11))

class AceBtn(Button):
    def __init__(self, val: int):
        super().__init__(label=f"A={val}", style=discord.ButtonStyle.primary if val==1 else discord.ButtonStyle.success)
        self.val = val
    async def callback(self, inter: discord.Interaction):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        if cid not in blackjack_sessions: 
            await inter.response.send_message("세션 없음", ephemeral=True); return
        sess = blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작 가능", ephemeral=True); return
        sess.ace_values[uid][self.view.card_index] = self.val
        sc = sess.score(uid)
        await inter.channel.send(f"**{uname}** A={self.val} 선택 → {' '.join(sess.players[uid])} (합계 {sc})")
        sess.actions[uid] = True
        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트** (합계 {sc})")

        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="bj", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlackjackPlayView(target_uid=u))

# ────────────────────────────────────────────────────────────────
# 🎮 블라인드 블랙잭 플레이 (개인 전용 버튼, 카드 비공개)
# ────────────────────────────────────────────────────────────────
class BlindPlayView(View):
    def __init__(self, target_uid: str):
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
            await inter.response.send_message("세션 없음", ephemeral=True); return
        sess = blind_blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작 가능", ephemeral=True); return

        card = sess.hit(uid)  # 비공개
        sc = sess.score(uid)
        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트** (합계 {sc} — 비공개)")
        else:
            await inter.channel.send(f"**{uname}** 히트 완료 (합계 {sc} — 비공개)")

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
            await inter.response.send_message("세션 없음", ephemeral=True); return
        sess = blind_blackjack_sessions[cid]
        if uid != self.view.target_uid:
            await inter.response.send_message("⛔ 본인만 조작 가능", ephemeral=True); return

        sess.stay(uid)
        sc = sess.score(uid)
        await inter.channel.send(f"**{uname}** 스테이 (합계 {sc} — 비공개)")

        if sess.everyone_acted():
            if sess.is_finished():
                await settle_and_end(inter, mode="blind", sess=sess)
            else:
                sess.reset_actions()
                for u in sess.players.keys():
                    if u not in sess.stayed and u not in sess.busted:
                        await inter.channel.send(f"<@{u}> 님 차례입니다.", view=BlindPlayView(target_uid=u))

# ────────────────────────────────────────────────────────────────
# 💰 정산/종료 (블랙잭·블라인드 공용)
#  - 승자: 버스트 아니고 최고점(≤21)
#  - 패자: 나머지 전원 (버스트 포함)
#  - 다 버스트: 전원 -자기 베팅
#  - 다수 승자: 패자들의 베팅 합을 승자 수로 균등 분배(나머지는 앞에서부터 +1)
#  - 모두 정산 후 시트 반영, 결과 표시, 덱 자동 셔플, 세션 삭제
# ────────────────────────────────────────────────────────────────
async def settle_and_end(inter: discord.Interaction, mode: str, sess):
    ch = inter.channel

    # 점수/상태 정리
    if mode == "bj":
        get_score = sess.score
        players_cards = sess.players  # 공개용
        title = "🃏 블랙잭 결과 발표"
    else:
        get_score = sess.score
        players_cards = None         # 비공개
        title = "🃏 블라인드 블랙잭 결과 발표"

    scores = {u: get_score(u) for u in sess.players}
    alive   = {u:s for u,s in scores.items() if s <= 21}
    bustedU = {u for u,s in scores.items() if s > 21}

    # 결과 라인(블라인드는 카드 미표시)
    lines = []
    for u in sess.players:
        member = next((m for m in ch.members if str(m.id)==u), None)
        name = member.display_name if member else f"UID:{u}"
        s = scores[u]
        state = "버스트 ❌" if s > 21 else f"합계 {s}"
        if players_cards is not None:
            lines.append(f"**{name}** → {' '.join(players_cards[u])} ({state}) / 베팅 {sess.bets.get(u,0)}")
        else:
            lines.append(f"**{name}** → ({state}, 카드 비공개) / 베팅 {sess.bets.get(u,0)}")

    # 승자/패자 결정
    if not alive:
        # 전원 버스트 → 전원 -베팅
        await ch.send(title + "\n" + "\n".join(lines) + "\n\n모두 버스트! 전원 베팅만큼 잃습니다.")
        for u, b in sess.bets.items():
            member = next((m for m in ch.members if str(m.id)==u), None)
            name = member.display_name if member else f"UID:{u}"
            new_bal = add_balance(u, name, -b)
            await ch.send(f"🔻 {name} (-{b}) → 총 {new_bal}")
    else:
        max_s = max(alive.values())
        winners = [u for u,s in alive.items() if s == max_s]
        losers  = [u for u in sess.players.keys() if u not in winners]
        pot_from_losers = sum(sess.bets.get(u,0) for u in losers)
        # 승자별 몫 = 자기 베팅 + (loser pot / winners 수), 나머지 1씩 앞에서부터
        base_share = pot_from_losers // len(winners)
        rem = pot_from_losers %  len(winners)

        # 패자 차감
        for u in losers:
            member = next((m for m in ch.members if str(m.id)==u), None)
            name = member.display_name if member else f"UID:{u}"
            b = sess.bets.get(u,0)
            new_bal = add_balance(u, name, -b)
            await ch.send(f"🔻 {name} (-{b}) → 총 {new_bal}")

        # 승자 지급
        for idx, u in enumerate(winners):
            member = next((m for m in ch.members if str(m.id)==u), None)
            name = member.display_name if member else f"UID:{u}"
            b = sess.bets.get(u,0)
            gain = b + base_share + (1 if idx < rem else 0)
            new_bal = add_balance(u, name, +gain)
            await ch.send(f"🏆 {name} (+{gain}) → 총 {new_bal}")

        # 승자 안내
        if len(winners)==1:
            wmem = next((m for m in ch.members if str(m.id)==winners[0]), None)
            wname = wmem.display_name if wmem else f"UID:{winners[0]}"
            await ch.send(f"결론: **{wname}** 승리! (최고 {max_s})")
        else:
            names = []
            for u in winners:
                mem = next((m for m in ch.members if str(m.id)==u), None)
                names.append(mem.display_name if mem else f"UID:{u}")
            await ch.send(f"결론: 🤝 공동 승리 — {', '.join(names)} (최고 {max_s})")

    # 최종 타이틀/라인 출력은 가장 위에서 이미 출력
    await ch.send(title + "\n" + "\n".join(lines))

    # 🔁 자동 셔플 + 세션 삭제
    shuffle_decks(sess.cid)
    if mode == "bj":
        del blackjack_sessions[sess.cid]
    else:
        del blind_blackjack_sessions[sess.cid]
    await ch.send("🎮 **게임 종료!** 새로운 게임은 `!세팅`으로 시작하세요.")

# ────────────────────────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
