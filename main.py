# 🔐 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import random, os, sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ────────────────────────────────────────────────────────────────
# ♣ 덱 관리
# ────────────────────────────────────────────────────────────────
channel_decks = {}
channel_indices = {}
suits = ['♠', '♥', '♦', '♣']
ranks = ['A'] + [str(n) for n in range(2, 11)] + ['J', 'Q', 'K']
deck = [f"{suit}{rank}" for suit in suits for rank in ranks]

def shuffle_all_decks(channel_id: str):
    channel_decks[channel_id] = {
        "blackjack": random.sample(deck, len(deck)),
        "blind_blackjack": random.sample(deck, len(deck)),
        "baccarat": random.sample(deck * 6, len(deck) * 6),
    }
    channel_indices[channel_id] = {"blackjack": 0, "blind_blackjack": 0, "baccarat": 0}

def ensure_channel_setup(channel_id: str):
    if channel_id not in channel_decks:
        shuffle_all_decks(channel_id)

def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

# ────────────────────────────────────────────────────────────────
# ⚙️ 기본 명령어
# ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f"✅ Logged in as {bot.user}")

@bot.command()
async def 세팅(ctx):
    await ctx.send("게임을 선택하세요.", view=GameMenu())

# ────────────────────────────────────────────────────────────────
# 🎮 메인 게임 메뉴
# ────────────────────────────────────────────────────────────────
class GameMenu(View):
    def __init__(self):
        super().__init__(timeout=None)
        # 1행 — 카드류
        self.add_item(GameButton("블랙잭", "blackjack", discord.ButtonStyle.danger, row=0))
        # 2행 — 간단 게임류
        self.add_item(GameButton("가위바위보", "rps", discord.ButtonStyle.primary, row=1))
        self.add_item(GameButton("홀짝", "odd_even", discord.ButtonStyle.primary, row=1))
        self.add_item(GameButton("야바위", "shell", discord.ButtonStyle.primary, row=1))
        # 3행 — 슬롯, 다이스
        self.add_item(GameButton("슬롯머신", "slot", discord.ButtonStyle.success, row=2))
        self.add_item(GameButton("다이스", "dice", discord.ButtonStyle.success, row=2))

class GameButton(discord.ui.Button):
    def __init__(self, label, custom_id, style, row):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        ensure_channel_setup(cid)
        ts = now_kst_str()

        # 🎮 블랙잭
        if self.custom_id == "blackjack":
            await inter.response.send_message(
                f"🃏 **블랙잭 세션 생성**\n플레이어 인원을 선택하세요.",
                view=PlayerCountSelectView(self.custom_id)
            )

        # ✂️ 가위바위보
        elif self.custom_id == "rps":
            result = random.choice(["가위", "바위", "보"])
            await inter.response.send_message(f"✂️ 가위바위보 결과: {result}\n{ts}")

        # ⚪ 홀짝
        elif self.custom_id == "odd_even":
            results = ["홀" if random.randint(1,6)%2 else "짝" for _ in range(3)]
            await inter.response.send_message(f"⚪ 홀짝 결과: {' '.join(results)}\n{ts}")

        # 🎲 야바위
        elif self.custom_id == "shell":
            result = random.choice(['OXX','XOX','XXO'])
            await inter.response.send_message(f"🎲 야바위 결과: {result}\n{ts}")

        # 🎰 슬롯머신
        elif self.custom_id == "slot":
            symbols = ['❤️','💔','💖','💝','🔴','🔥','🦋','💥']
            reels = [random.choice(symbols) for _ in range(3)]
            if reels.count(reels[0]) == 3:
                guide = "💥 잭팟! (5배)"
            elif len(set(reels)) == 2:
                guide = "💎 더블! (2배)"
            else:
                guide = "❌ 꽝!"
            await inter.response.send_message(f"{' '.join(reels)}\n{guide}\n{ts}")

        # 🎲 다이스
        elif self.custom_id == "dice":
            await inter.response.send_message(
                f"{inter.user.mention} 주사위를 선택하세요.",
                view=DiceView(owner_id=inter.user.id)
            )

# ────────────────────────────────────────────────────────────────
# 🎲 다이스 시스템
# ────────────────────────────────────────────────────────────────
class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id

    async def callback(self, inter: discord.Interaction):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("당신의 다이스가 아닙니다.", ephemeral=True)
            return
        roll = random.randint(1, self.sides)
        await inter.response.send_message(f"🎲 1d{self.sides} 결과: {roll}\n{now_kst_str()}")

class DiceView(View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.add_item(DiceButton(6, discord.ButtonStyle.danger, owner_id))
        self.add_item(DiceButton(10, discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))

# ────────────────────────────────────────────────────────────────
# 👥 블랙잭 인원 선택
# ────────────────────────────────────────────────────────────────
class PlayerCountSelectView(View):
    def __init__(self, game_type: str):
        super().__init__(timeout=None)
        self.game_type = game_type
        for n in range(2, 5):
            self.add_item(PlayerCountButton(n, game_type))

class PlayerCountButton(Button):
    def __init__(self, count, game_type):
        super().__init__(label=f"{count}명", style=discord.ButtonStyle.primary)
        self.count = count
        self.game_type = game_type

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        ensure_channel_setup(cid)
        deck_ref = channel_decks[cid][self.game_type]
        blackjack_sessions[cid] = BlackjackSession(cid, deck_ref, self.count)
        await inter.response.send_message(
            f"🃏 **블랙잭 세션({self.count}명)** 생성 완료!\n`!참가` 명령어로 참가하세요."
        )

# ────────────────────────────────────────────────────────────────
# 🃏 블랙잭 세션 관리
# ────────────────────────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, cid, deck_ref, max_players):
        self.cid = cid
        self.deck = deck_ref
        self.max_players = max_players
        self.players = {}
        self.finished = set()
        self.busted = set()
        self.ace_values = {}

    def deal_initial(self, uid):
        if uid not in self.players:
            self.players[uid] = [self.deck.pop(), self.deck.pop()]
            self.ace_values[uid] = {}
        return self.players[uid]

    def hit(self, uid):
        card = self.deck.pop()
        self.players[uid].append(card)
        return card

    def calc(self, uid):
        cards = self.players[uid]
        total = 0
        for i, c in enumerate(cards):
            r = c[1:]
            if r in ["J", "Q", "K"]:
                total += 10
            elif r == "A":
                total += self.ace_values.get(uid, {}).get(i, 11)
            else:
                total += int(r)
        return total

    def set_ace(self, uid, idx, val):
        self.ace_values[uid][idx] = val

    def stay(self, uid):
        self.finished.add(uid)

    def done(self):
        return len(self.players) >= self.max_players and \
            all(uid in self.finished or self.calc(uid) > 21 for uid in self.players)

blackjack_sessions = {}

# ────────────────────────────────────────────────────────────────
# 🎮 참가 커맨드
# ────────────────────────────────────────────────────────────────
@bot.command()
async def 참가(ctx):
    cid, uid, uname = str(ctx.channel.id), str(ctx.author.id), ctx.author.display_name
    if cid not in blackjack_sessions:
        await ctx.send("❌ 블랙잭 세션이 없습니다.")
        return
    sess = blackjack_sessions[cid]
    if len(sess.players) >= sess.max_players and uid not in sess.players:
        await ctx.send("🚫 참가 인원 초과!")
        return
    cards = sess.deal_initial(uid)
    sc = sess.calc(uid)
    await ctx.send(f"**{uname}** 참가 완료!\n🂠 {' '.join(cards)} (합계 {sc})", view=BlackjackPlayView(uid))
    if len(sess.players) == sess.max_players:
        await ctx.send(f"🎮 모든 참가자({sess.max_players}명) 준비 완료! 게임 시작!")

# ────────────────────────────────────────────────────────────────
# 🎮 플레이
# ────────────────────────────────────────────────────────────────
class BlackjackPlayView(View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid
        self.add_item(HitButton())
        self.add_item(StayButton())

class HitButton(Button):
    def __init__(self):
        super().__init__(label="히트", style=discord.ButtonStyle.success)

    async def callback(self, inter):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        sess = blackjack_sessions[cid]
        new_card = sess.hit(uid)
        idx = len(sess.players[uid]) - 1
        sc = sess.calc(uid)

        if "A" in new_card:
            await inter.channel.send(f"**{uname}** 새 카드 {new_card}, A값 선택!", view=AceChoiceView(uid, idx))
            return

        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트!** (합계 {sc})")
        else:
            await inter.channel.send(f"**{uname}** {' '.join(sess.players[uid])} (합계 {sc})", view=BlackjackPlayView(uid))
        if sess.done():
            await announce_result(inter, sess)

class StayButton(Button):
    def __init__(self):
        super().__init__(label="스테이", style=discord.ButtonStyle.danger)

    async def callback(self, inter):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        sess = blackjack_sessions[cid]
        sess.stay(uid)
        sc = sess.calc(uid)
        await inter.channel.send(f"**{uname}** 스테이. (합계 {sc})")
        if sess.done():
            await announce_result(inter, sess)

# ────────────────────────────────────────────────────────────────
# 🅰️ A 선택
# ────────────────────────────────────────────────────────────────
class AceChoiceView(View):
    def __init__(self, uid, idx):
        super().__init__(timeout=None)
        self.uid = uid
        self.idx = idx
        self.add_item(AceButton(1))
        self.add_item(AceButton(11))

class AceButton(Button):
    def __init__(self, val):
        super().__init__(label=f"A={val}", style=discord.ButtonStyle.primary if val == 1 else discord.ButtonStyle.success)
        self.val = val

    async def callback(self, inter):
        cid, uid, uname = str(inter.channel.id), str(inter.user.id), inter.user.display_name
        sess = blackjack_sessions[cid]
        sess.set_ace(uid, self.view.idx, self.val)
        sc = sess.calc(uid)
        await inter.channel.send(f"**{uname}** A={self.val} 선택 → {' '.join(sess.players[uid])} (합계 {sc})", view=BlackjackPlayView(uid))
        if sc > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트!** (합계 {sc})")
        if sess.done():
            await announce_result(inter, sess)

# ────────────────────────────────────────────────────────────────
# 🏁 결과 + 자동 셔플
# ────────────────────────────────────────────────────────────────
async def announce_result(inter, sess):
    ch = inter.channel
    lines, scores = [], {}
    for uid, cards in sess.players.items():
        member = next((m for m in ch.members if str(m.id) == uid), None)
        name = member.display_name if member else "Unknown"
        s = sess.calc(uid)
        scores[uid] = s
        state = "버스트 ❌" if s > 21 else f"합계 {s}"
        lines.append(f"**{name}** → {' '.join(cards)} ({state})")

    alive = {uid:s for uid,s in scores.items() if s<=21}
    if not alive:
        winner = "모두 버스트, 무승부!"
    else:
        max_s = max(alive.values())
        win_ids = [uid for uid,s in alive.items() if s==max_s]
        if len(win_ids)==1:
            member = next((m for m in ch.members if str(m.id)==win_ids[0]),None)
            winner = f"🏆 승자: **{member.display_name}** ({max_s})"
        else:
            names = [next((m.display_name for m in ch.members if str(m.id)==i),'Unknown') for i in win_ids]
            winner = f"🤝 공동 승리: {', '.join(names)} ({max_s})"

    await ch.send("🃏 **블랙잭 결과 발표**\n" + "\n".join(lines) + f"\n\n{winner}")
    shuffle_all_decks(sess.cid)
    del blackjack_sessions[sess.cid]
    await ch.send("🔄 카드 덱이 자동으로 셔플되었습니다. 새로운 게임을 시작하세요.")

# ────────────────────────────────────────────────────────────────
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
