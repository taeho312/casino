# 🔐 라이브러리 및 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import random
import os
import json
import sys
import asyncio

KST = timezone(timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ────────────────────────────────────────────────────────────────
# 📦 채널 단위 카드 덱 저장소
# ────────────────────────────────────────────────────────────────
channel_decks = {}
channel_indices = {}

suits = ['♠', '♥', '♦', '♣']
ranks = ['A'] + [str(n) for n in range(2, 11)] + ['J', 'Q', 'K']
deck = [f"{suit}{rank}" for suit in suits for rank in ranks]

# ────────────────────────────────────────────────────────────────
# 🔐 환경변수 및 구글 시트 인증
# ────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
SHEET_KEY = os.getenv("SHEET_KEY")

missing = [k for k, v in {
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "GOOGLE_CREDS": GOOGLE_CREDS,
    "SHEET_KEY": SHEET_KEY
}.items() if not v]
if missing:
    print(f"누락된 환경변수: {', '.join(missing)}")
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
    print("구글 스프레드시트 인증/접속 실패:", e)
    sys.exit(1)

def ws(title: str):
    return gclient.open_by_key(SHEET_KEY).worksheet(title)

# ────────────────────────────────────────────────────────────────
# 🧰 유틸
# ────────────────────────────────────────────────────────────────
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

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

# ────────────────────────────────────────────────────────────────
# ⚙️ 기본 명령어
# ────────────────────────────────────────────────────────────────
@bot.command()
async def 세팅(ctx):
    await ctx.send("요청이 확인되었습니다. 원하시는 게임 버튼을 선택해 주십시오.", view=GameMenu())

@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f'Logged in as {bot.user} ({bot.user.id})')

# ────────────────────────────────────────────────────────────────
# 🎮 게임 메뉴
# ────────────────────────────────────────────────────────────────
class GameMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GameButton("블랙잭", "blackjack", discord.ButtonStyle.danger, row=0))

class GameButton(discord.ui.Button):
    def __init__(self, label: str, custom_id: str, style: discord.ButtonStyle, row: int):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        await interaction.response.send_message(
            f"🃏 **블랙잭 세션 시작 준비 완료!**\n`블랙잭 시작` 버튼을 눌러 세션을 열어주세요.",
            view=CardDrawView(self.custom_id)
        )

# ────────────────────────────────────────────────────────────────
# 🃏 블랙잭 전용 카드 배분 시스템 (A 선택 가능)
# ────────────────────────────────────────────────────────────────
class BlackjackSession:
    def __init__(self, channel_id, deck_ref):
        self.channel_id = channel_id
        self.deck = deck_ref
        self.players = {}          # {user_id: [cards]}
        self.finished = set()
        self.busted = set()
        self.ace_values = {}       # {user_id: {card_index: 1 or 11}}

    def deal_initial(self, user_id, user_name):
        if user_id not in self.players:
            self.players[user_id] = [self.deck.pop(), self.deck.pop()]
            self.ace_values[user_id] = {}
        return self.players[user_id]

    def hit(self, user_id):
        if user_id in self.players and self.deck:
            card = self.deck.pop()
            self.players[user_id].append(card)
        return self.players[user_id]

    def stay(self, user_id):
        self.finished.add(user_id)

    def all_ready(self):
        return len(self.players) >= 2

    def all_done(self):
        total_players = len(self.players)
        done_count = len(self.finished.union(self.busted))
        return total_players >= 2 and done_count == total_players

    def calculate_score(self, user_id):
        cards = self.players.get(user_id, [])
        total = 0
        for idx, c in enumerate(cards):
            rank = c[1:]
            if rank in ["J", "Q", "K"]:
                total += 10
            elif rank == "A":
                chosen = self.ace_values.get(user_id, {}).get(idx, 11)
                total += chosen
            else:
                total += int(rank)
        return total

    def set_ace_value(self, user_id, card_index, value):
        if user_id not in self.ace_values:
            self.ace_values[user_id] = {}
        self.ace_values[user_id][card_index] = value

    def is_busted(self, user_id):
        return self.calculate_score(user_id) > 21


blackjack_sessions = {}  # {channel_id: BlackjackSession}

class CardDrawView(discord.ui.View):
    def __init__(self, game_type: str):
        super().__init__(timeout=None)
        self.game_type = game_type
        self.add_item(StartBlackjackButton(discord.ButtonStyle.danger, game_type))

class StartBlackjackButton(discord.ui.Button):
    def __init__(self, style: discord.ButtonStyle, game_type: str):
        super().__init__(label="블랙잭 시작", style=style)
        self.game_type = game_type

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        deck_ref = channel_decks[channel_id][self.game_type]
        blackjack_sessions[channel_id] = BlackjackSession(channel_id, deck_ref)
        await interaction.response.send_message(
            f"🃏 **블랙잭 세션이 시작되었습니다!**\n두 명의 플레이어가 참가할 수 있습니다.\n`!참가` 명령어로 참가하세요."
        )

# ────────────────────────────────────────────────────────────────
# 🎮 참가 및 진행
# ────────────────────────────────────────────────────────────────
@bot.command(name="참가", help="블랙잭 세션에 참가합니다.")
async def 참가(ctx):
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name

    if channel_id not in blackjack_sessions:
        await ctx.send("세션이 없습니다. 먼저 블랙잭 버튼으로 세션을 생성하세요.")
        return

    session = blackjack_sessions[channel_id]
    if len(session.players) >= 2 and user_id not in session.players:
        await ctx.send("이미 두 명이 참가했습니다.")
        return

    cards = session.deal_initial(user_id, user_name)
    score = session.calculate_score(user_id)
    await ctx.send(f"**{user_name}** 님이 참가했습니다.\n🂠 카드: {' '.join(cards)} (합계: {score})", view=BlackjackPlayView(user_id))

    if session.all_ready():
        await ctx.send("두 명의 참가자가 준비되었습니다. 게임 시작!")

class BlackjackPlayView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(HitButton())
        self.add_item(StayButton())

class HitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="히트", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if channel_id not in blackjack_sessions:
            await interaction.response.send_message("현재 세션이 없습니다.", ephemeral=True)
            return

        session = blackjack_sessions[channel_id]
        if user_id not in session.players:
            await interaction.response.send_message("참가자가 아닙니다.", ephemeral=True)
            return

        new_cards = session.hit(user_id)
        score = session.calculate_score(user_id)
        new_card = new_cards[-1]
        new_index = len(new_cards) - 1

        # A 등장 시 선택 버튼 표시
        if "A" in new_card:
            await interaction.response.edit_message(
                content=f"**{user_name}** 님의 카드: {' '.join(new_cards)} (합계: {score})\n🂠 새 카드 {new_card}의 값을 선택하세요.",
                view=AceChoiceView(user_id, new_index)
            )
            return

        # 버스트
        if score > 21:
            session.busted.add(user_id)
            await interaction.response.edit_message(
                content=f"**{user_name}** 카드: {' '.join(new_cards)} (합계: {score}) 💥 **버스트! (패배)**",
                view=None
            )
        else:
            await interaction.response.edit_message(
                content=f"**{user_name}** 카드: {' '.join(new_cards)} (합계: {score})",
                view=self
            )

        if session.all_done():
            await announce_blackjack_result(interaction, session)

class StayButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="스테이", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if channel_id not in blackjack_sessions:
            await interaction.response.send_message("세션이 없습니다.", ephemeral=True)
            return

        session = blackjack_sessions[channel_id]
        session.stay(user_id)
        score = session.calculate_score(user_id)
        await interaction.response.edit_message(
            content=f"**{user_name}** 님이 스테이했습니다. (합계: {score})",
            view=None
        )
        if session.all_done():
            await announce_blackjack_result(interaction, session)

# ────────────────────────────────────────────────────────────────
# 🅰️ A값 선택 버튼
# ────────────────────────────────────────────────────────────────
class AceChoiceView(discord.ui.View):
    def __init__(self, user_id: str, card_index: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.card_index = card_index
        self.add_item(AceButton(1, discord.ButtonStyle.primary))
        self.add_item(AceButton(11, discord.ButtonStyle.success))

class AceButton(discord.ui.Button):
    def __init__(self, value: int, style: discord.ButtonStyle):
        super().__init__(label=f"A={value}", style=style)
        self.value = value

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if channel_id not in blackjack_sessions:
            await interaction.response.send_message("세션이 없습니다.", ephemeral=True)
            return

        session = blackjack_sessions[channel_id]
        session.set_ace_value(user_id, self.view.card_index, self.value)
        score = session.calculate_score(user_id)
        cards = session.players[user_id]

        if score > 21:
            session.busted.add(user_id)
            await interaction.response.edit_message(
                content=f"**{user_name}** A={self.value} 선택 → {' '.join(cards)} (합계: {score}) 💥 **버스트! (패배)**",
                view=None
            )
        else:
            await interaction.response.edit_message(
                content=f"**{user_name}** A={self.value} 선택 → {' '.join(cards)} (합계: {score})",
                view=BlackjackPlayView(user_id)
            )

        if session.all_done():
            await announce_blackjack_result(interaction, session)

# ────────────────────────────────────────────────────────────────
# 🏁 결과 발표
# ────────────────────────────────────────────────────────────────
async def announce_blackjack_result(interaction: discord.Interaction, session):
    channel = interaction.channel
    result_lines = []
    scores = {}

    for uid, cards in session.players.items():
        member = next((m for m in channel.members if str(m.id) == uid), None)
        name = member.display_name if member else "Unknown"
        score = session.calculate_score(uid)
        scores[uid] = score
        state = "버스트 ❌" if uid in session.busted else f"합계: {score}"
        result_lines.append(f"**{name}** → {' '.join(cards)} ({state})")

    alive = {uid: sc for uid, sc in scores.items() if uid not in session.busted and sc <= 21}
    if not alive:
        winner_text = "모두 버스트! 무승부입니다."
    else:
        max_score = max(alive.values())
        winners = [uid for uid, sc in alive.items() if sc == max_score]
        if len(winners) == 1:
            member = next((m for m in channel.members if str(m.id) == winners[0]), None)
            winner_text = f"🏆 승자: **{member.display_name}** (합계 {max_score})"
        else:
            names = [next((m.display_name for m in channel.members if str(m.id) == uid), 'Unknown') for uid in winners]
            winner_text = f"🤝 공동 승리: {', '.join(names)} (합계 {max_score})"

    del blackjack_sessions[session.channel_id]
    await channel.send("🃏 **블랙잭 결과 발표**\n" + "\n".join(result_lines) + f"\n\n{winner_text}")

# ────────────────────────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
