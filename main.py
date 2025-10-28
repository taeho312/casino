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

def _parse_names_and_amount(args):
    if len(args) < 2:
        return None, "최소 1명 이상의 이름과 수치를 입력하십시오. 예) !추가 홍길동 김철수 5"
    amount_str = args[-1]
    if not amount_str.isdigit():
        return None, "수치는 양의 정수여야 합니다."
    amount = int(amount_str)
    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)
    if not names:
        return None, "유효한 이름이 없습니다."
    names = list(dict.fromkeys(names))
    return (names, amount), None

# ────────────────────────────────────────────────────────────────
# 🃏 덱 관련 함수 (채널 단위)
# ────────────────────────────────────────────────────────────────
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

@bot.command()
async def 작동(ctx):
    await ctx.send("현재 정상 작동 중입니다.")

@bot.event
async def on_ready():
    bot.add_view(GameMenu())
    print(f'Logged in as {bot.user} ({bot.user.id})')

@bot.command(name="접속", help="현재 봇이 정상 작동 중인지 확인합니다. 예) !접속")
async def 접속(ctx):
    await ctx.send(f"현재 봇이 정상적으로 작동 중입니다.\n{now_kst_str()}")

@bot.command(name="시트테스트", help="연결 확인 시트 테스트")
async def 시트테스트(ctx):
    try:
        sh = ws("연결 확인")
        sh.update_acell("A1", f"연결 OK @ {now_kst_str()}")
        val = sh.acell("A1").value
        await ctx.send(f"연동 확인 완료 ✅\n{val}\n{now_kst_str()}")
    except Exception as e:
        await ctx.send(f"시트 접근 실패: {e}\n{now_kst_str()}")

# ────────────────────────────────────────────────────────────────
# 🎮 게임 메뉴
# ────────────────────────────────────────────────────────────────
class GameMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GameButton("블랙잭", "blackjack", discord.ButtonStyle.danger, row=0))
        self.add_item(GameButton("블라인드 블랙잭", "blind_blackjack", discord.ButtonStyle.danger, row=0))
        self.add_item(GameButton("바카라", "baccarat", discord.ButtonStyle.danger, row=0))
        self.add_item(GameButton("가위바위보", "rps", discord.ButtonStyle.primary, row=1))
        self.add_item(GameButton("야바위", "shell", discord.ButtonStyle.primary, row=1))
        self.add_item(GameButton("홀짝", "odd_even", discord.ButtonStyle.primary, row=1))
        self.add_item(GameButton("슬롯머신", "slot", discord.ButtonStyle.success, row=2))
        self.add_item(GameButton("로또", "lotto", discord.ButtonStyle.success, row=2))
        self.add_item(GameButton("셔플", "shuffle", discord.ButtonStyle.secondary, row=2))

class GameButton(discord.ui.Button):
    def __init__(self, label: str, custom_id: str, style: discord.ButtonStyle, row: int):
        super().__init__(label=label, custom_id=custom_id, style=style, row=row)

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        timestamp = now_kst_str()

        if self.custom_id in ["blackjack", "blind_blackjack", "baccarat"]:
            await interaction.response.send_message(
                f"카드 배분 옵션을 선택해 주십시오. (2장, 1장)\n게임: {self.label}\n{timestamp}",
                view=CardDrawView(self.custom_id),
                ephemeral=False
            )
        elif self.custom_id == "shuffle":
            await interaction.response.send_message(
                f"셔플할 게임을 선택해 주십시오.\n{timestamp}",
                view=ShuffleSelectView(),
                ephemeral=False
            )
        elif self.custom_id == "rps":
            result = random.choice(["가위", "바위", "보"])
            await interaction.response.send_message(f"가위바위보 결과: {result}\n{timestamp}")
        elif self.custom_id == "odd_even":
            results = []
            for _ in range(3):
                roll = random.randint(1, 6)
                results.append("홀" if roll % 2 else "짝")
            await interaction.response.send_message(f"홀짝 결과: {' '.join(results)}\n{timestamp}")
        elif self.custom_id == "lotto":
            numbers = sorted(random.sample(range(1, 46), 6))
            await interaction.response.send_message(f"로또 번호: {', '.join(map(str, numbers))}\n{timestamp}")
        elif self.custom_id == "slot":
            symbols = ['❤️', '💔', '💖', '💝', '🔴', '🔥', '🦋', '💥']
            reels = [random.choice(symbols) for _ in range(3)]
            if reels.count(reels[0]) == 3:
                guide = "🎰 잭팟! (5배)"
            elif len(set(reels)) == 2:
                guide = "더블! (2배)"
            else:
                guide = "꽝!"
            await interaction.response.send_message(f"{' '.join(reels)}\n{guide}\n{timestamp}")
        elif self.custom_id == "shell":
            result = random.choice(['OXX', 'XOX', 'XXO'])
            await interaction.response.send_message(f"야바위 결과: {result}\n{timestamp}")
        else:
            await interaction.response.send_message("지원되지 않는 게임입니다.", ephemeral=False)

# ────────────────────────────────────────────────────────────────
# 🃏 카드 배분
# ────────────────────────────────────────────────────────────────
class CardDrawView(discord.ui.View):
    def __init__(self, game_type: str):
        super().__init__(timeout=60)
        self.game_type = game_type
        self.add_item(CardDrawButton("[2장]", 2, discord.ButtonStyle.danger, game_type))
        self.add_item(CardDrawButton("[1장]", 1, discord.ButtonStyle.primary, game_type))

class CardDrawButton(discord.ui.Button):
    def __init__(self, label: str, draw_count: int, style: discord.ButtonStyle, game_type: str):
        super().__init__(label=label, style=style, custom_id=f"draw_{label}_{game_type}")
        self.draw_count = draw_count
        self.game_type = game_type

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        timestamp = now_kst_str()

        deck_ref = channel_decks[channel_id][self.game_type]
        idx = channel_indices[channel_id][self.game_type]

        lines = []
        for _ in range(self.draw_count):
            if not deck_ref:
                lines.append("카드가 모두 소진되었습니다. 셔플이 필요합니다.")
                break

            name = chr(65 + (idx % 26))  # A~Z
            drawn = [deck_ref.pop() for _ in range(self.draw_count)]
            lines.append(f"{name}: {' '.join(drawn)}")
            idx += 1
            if idx >= 26:
                lines.append("플레이어명을 A부터 다시 시작합니다.")
                idx = 0

        channel_indices[channel_id][self.game_type] = idx
        remaining = len(deck_ref)
        response_text = "\n".join(lines) + f"\n남은 카드 수: {remaining}장\n{timestamp}"
        await interaction.response.send_message(response_text, ephemeral=False)

# ────────────────────────────────────────────────────────────────
# 🔄 셔플
# ────────────────────────────────────────────────────────────────
class ShuffleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.add_item(ShuffleButton("블랙잭 셔플", "blackjack", discord.ButtonStyle.danger))
        self.add_item(ShuffleButton("블라인드 블랙잭 셔플", "blind_blackjack", discord.ButtonStyle.primary))
        self.add_item(ShuffleButton("바카라 셔플", "baccarat", discord.ButtonStyle.success))

class ShuffleButton(discord.ui.Button):
    def __init__(self, label: str, game_key: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"shuffle_{game_key}")
        self.game_key = game_key

    async def callback(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        ensure_channel_setup(channel_id)
        timestamp = now_kst_str()

        if self.game_key == "baccarat":
            channel_decks[channel_id][self.game_key] = random.sample(deck * 6, len(deck) * 6)
        else:
            channel_decks[channel_id][self.game_key] = random.sample(deck, len(deck))
        channel_indices[channel_id][self.game_key] = 0

        await interaction.response.send_message(f"{self.label} 완료!\n{timestamp}", ephemeral=False)

# ────────────────────────────────────────────────────────────────
# 🎲 다이스 버튼
# ────────────────────────────────────────────────────────────────
class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("명령어 실행자만 사용할 수 있습니다.", ephemeral=True)
            return
        roll = random.randint(1, self.sides)
        await interaction.response.send_message(f"1d{self.sides} 결과: {roll}\n{now_kst_str()}")

class DiceView(View):
    def __init__(self, owner_id: int, timeout: int = None):
        super().__init__(timeout=timeout)
        self.add_item(DiceButton(6, discord.ButtonStyle.danger, owner_id))
        self.add_item(DiceButton(10, discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))
        self.message = None

@bot.command(name="다이스", help="버튼으로 1d6/1d10/1d100 굴리기")
async def 다이스(ctx):
    view = DiceView(owner_id=ctx.author.id)
    msg = await ctx.send(f"{ctx.author.mention} 주사위를 선택하세요.\n{now_kst_str()}", view=view)
    view.message = msg

# ────────────────────────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
