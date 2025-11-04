# 🔐 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import random, os, json, sys
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
    """모든 게임용 덱을 새로 셔플"""
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
@bot.command()
async def 세팅(ctx):
    await ctx.send("게임 메뉴를 선택하세요.", view=GameMenu())

@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f"✅ Logged in as {bot.user}")

# ────────────────────────────────────────────────────────────────
# 🎮 게임 메뉴
# ────────────────────────────────────────────────────────────────
class GameMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GameButton("블랙잭", "blackjack", discord.ButtonStyle.danger))

class GameButton(discord.ui.Button):
    def __init__(self, label, custom_id, style):
        super().__init__(label=label, custom_id=custom_id, style=style)

    async def callback(self, interaction: discord.Interaction):
        ensure_channel_setup(str(interaction.channel.id))
        await interaction.response.send_message(
            f"🃏 **블랙잭 세션 생성**\n플레이어 인원을 선택하세요.",
            view=PlayerCountSelectView(self.custom_id)
        )

# ────────────────────────────────────────────────────────────────
# 👥 인원 수 선택 버튼
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

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        deck_ref = channel_decks[channel_id][self.game_type]
        blackjack_sessions[channel_id] = BlackjackSession(channel_id, deck_ref, self.count)
        await interaction.response.send_message(
            f"🃏 **블랙잭 세션({self.count}명)** 이 시작되었습니다!\n플레이어는 `!참가`로 입장하세요."
        )

# ────────────────────────────────────────────────────────────────
# 🃏 블랙잭 세션
# ────────────────────────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, channel_id, deck_ref, max_players):
        self.channel_id = channel_id
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

    def calculate_score(self, uid):
        cards = self.players[uid]
        total = 0
        for idx, c in enumerate(cards):
            r = c[1:]
            if r in ["J", "Q", "K"]:
                total += 10
            elif r == "A":
                total += self.ace_values.get(uid, {}).get(idx, 11)
            else:
                total += int(r)
        return total

    def set_ace_value(self, uid, idx, val):
        if uid not in self.ace_values:
            self.ace_values[uid] = {}
        self.ace_values[uid][idx] = val

    def stay(self, uid):
        self.finished.add(uid)

    def is_done(self):
        return len(self.players) >= self.max_players and \
               all(uid in self.finished or self.calculate_score(uid) > 21 for uid in self.players)

# ────────────────────────────────────────────────────────────────
# 🎮 참가 명령어
# ────────────────────────────────────────────────────────────────
blackjack_sessions = {}

@bot.command(name="참가")
async def 참가(ctx):
    cid = str(ctx.channel.id)
    uid = str(ctx.author.id)
    uname = ctx.author.display_name

    if cid not in blackjack_sessions:
        await ctx.send("❌ 현재 블랙잭 세션이 없습니다.")
        return

    sess = blackjack_sessions[cid]
    if len(sess.players) >= sess.max_players and uid not in sess.players:
        await ctx.send("🚫 참가 인원이 이미 꽉 찼습니다.")
        return

    cards = sess.deal_initial(uid)
    score = sess.calculate_score(uid)
    await ctx.send(f"**{uname}** 참가 완료!\n🂠 카드: {' '.join(cards)} (합계 {score})", view=BlackjackPlayView(uid))

    if len(sess.players) == sess.max_players:
        await ctx.send(f"모든 참가자({sess.max_players}명) 준비 완료! 게임 시작 🎮")

# ────────────────────────────────────────────────────────────────
# 🎮 플레이 버튼
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

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        uid = str(inter.user.id)
        uname = inter.user.display_name
        sess = blackjack_sessions[cid]

        new_card = sess.hit(uid)
        new_index = len(sess.players[uid]) - 1
        score = sess.calculate_score(uid)

        # A 선택 필요 시
        if "A" in new_card:
            await inter.channel.send(
                f"**{uname}** → 새 카드 {new_card}\nA의 값을 선택하세요.",
                view=AceChoiceView(uid, new_index)
            )
            return

        if score > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트!** {' '.join(sess.players[uid])} (합계 {score})")
        else:
            await inter.channel.send(f"**{uname}** → {' '.join(sess.players[uid])} (합계 {score})", view=BlackjackPlayView(uid))

        if sess.is_done():
            await announce_result(inter, sess)

class StayButton(Button):
    def __init__(self):
        super().__init__(label="스테이", style=discord.ButtonStyle.danger)

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        uid = str(inter.user.id)
        uname = inter.user.display_name
        sess = blackjack_sessions[cid]

        sess.stay(uid)
        score = sess.calculate_score(uid)
        await inter.channel.send(f"**{uname}** 스테이. (합계 {score})")

        if sess.is_done():
            await announce_result(inter, sess)

# ────────────────────────────────────────────────────────────────
# 🅰️ A 값 선택 버튼
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

    async def callback(self, inter: discord.Interaction):
        cid = str(inter.channel.id)
        uid = str(inter.user.id)
        uname = inter.user.display_name
        sess = blackjack_sessions[cid]

        sess.set_ace_value(uid, self.view.idx, self.val)
        score = sess.calculate_score(uid)
        await inter.channel.send(f"**{uname}** A={self.val} 선택 → {' '.join(sess.players[uid])} (합계 {score})", view=BlackjackPlayView(uid))

        if score > 21:
            sess.busted.add(uid)
            await inter.channel.send(f"💥 **{uname} 버스트!** (합계 {score})")

        if sess.is_done():
            await announce_result(inter, sess)

# ────────────────────────────────────────────────────────────────
# 🏁 결과 + 자동 셔플
# ────────────────────────────────────────────────────────────────
async def announce_result(inter: discord.Interaction, sess: BlackjackSession):
    ch = inter.channel
    results, scores = [], {}
    for uid, cards in sess.players.items():
        member = next((m for m in ch.members if str(m.id) == uid), None)
        name = member.display_name if member else "Unknown"
        sc = sess.calculate_score(uid)
        scores[uid] = sc
        state = "버스트 ❌" if sc > 21 else f"합계 {sc}"
        results.append(f"**{name}** → {' '.join(cards)} ({state})")

    # 승자 계산
    alive = {uid: s for uid, s in scores.items() if s <= 21}
    if not alive:
        winner = "모두 버스트! 무승부."
    else:
        max_s = max(alive.values())
        win_ids = [uid for uid, s in alive.items() if s == max_s]
        if len(win_ids) == 1:
            member = next((m for m in ch.members if str(m.id) == win_ids[0]), None)
            winner = f"🏆 승자: **{member.display_name}** (합계 {max_s})"
        else:
            names = [next((m.display_name for m in ch.members if str(m.id) == i), "Unknown") for i in win_ids]
            winner = f"🤝 공동 승리: {', '.join(names)} (합계 {max_s})"

    await ch.send("🃏 **블랙잭 결과 발표**\n" + "\n".join(results) + f"\n\n{winner}")

    # 🔁 자동 셔플
    shuffle_all_decks(sess.channel_id)
    del blackjack_sessions[sess.channel_id]
    await ch.send("🔄 카드 덱이 자동으로 셔플되었습니다. 새로운 게임을 시작할 수 있습니다.")

# ────────────────────────────────────────────────────────────────
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
