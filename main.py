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
import re
import asyncio

KST = timezone(timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

user_decks = {}
user_indices = {}

suits = ['♠', '♥', '♦', '♣']
ranks = ['A'] + [str(n) for n in range(2, 11)] + ['J', 'Q', 'K']
deck = [f"{suit}{rank}" for suit in suits for rank in ranks]

# 🔐 환경변수 확인
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
SHEET_KEY = os.getenv("SHEET_KEY")

missing = [k for k, v in {
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "GOOGLE_CREDS": GOOGLE_CREDS,
    "SHEET_KEY": SHEET_KEY
}.items() if not v]
if missing:
    print(f"❌ 누락된 환경변수: {', '.join(missing)}")
    sys.exit(1)

# 🔐 구글 시트 인증
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
try:
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gclient = gspread.authorize(creds)
    sheet = gclient.open_by_key(SHEET_KEY).sheet1  # 기본은 1번째 시트
except Exception as e:
    print("❌ 구글 스프레드시트 인증/접속 실패:", e)
    sys.exit(1)

# 🧰 유틸
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

DICE_EMOJI = {
    1: "🎲1", 2: "🎲2", 3: "🎲3",
    4: "🎲4", 5: "🎲5", 6: "🎲6"
}

# 다중 이름 파서: 공백/쉼표 섞여도 처리
def _parse_names_and_amount(args):
    """
    args 예: ("홍길동","김철수","5")  또는 ("홍길동,김철수","5")
    returns: (names:list[str], amount:int)  또는 (None, error_msg)
    """
    if len(args) < 2:
        return None, "⚠️ 최소 1명 이상의 이름과 수치를 입력하세요. 예) `!추가 홍길동 김철수 5`"

    amount_str = args[-1]
    if not amount_str.isdigit():
        return None, "⚠️ 수치는 양의 정수여야 합니다. 예) `!추가 홍길동 김철수 5`"
    amount = int(amount_str)

    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)

    if not names:
        return None, "⚠️ 유효한 이름이 없습니다. 예) `!추가 홍길동 김철수 5`"

    # 같은 이름이 여러 번 입력되면 중복 제거(순서 유지)
    names = list(dict.fromkeys(names))
    return (names, amount), None

def shuffle_all_decks(user_id):
  user_decks[user_id] = {
    "blackjack": random.sample(deck, len(deck)),
    "blind_blackjack": random.sample(deck, len(deck))
  }
  user_indices[user_id] = {"blackjack": 0, "blind_blackjack": 0}
  
def ensure_user_setup(user_id):
  if user_id not in user_decks:
    shuffle_all_decks(user_id)

@bot.command() async def 세팅(ctx):
  await ctx.send("안녕하세요? 원하시는 게임 버튼을 클릭해주세요:", view=GameMenu())

@bot.command() async def 작동(ctx):
  await ctx.send("현재 정상 작동 중입니다.")

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user} ({bot.user.id})')

@bot.command(name="접속", help="현재 봇이 정상 작동 중인지 확인합니다. 만약 봇이 응답하지 않으면 접속 오류입니다. 예) !접속")
async def 접속(ctx):
    timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    await ctx.send(f"현재 봇이 구동 중입니다.\n{timestamp}")

# ✅ 연결 테스트용 커맨드 (원하면 삭제 가능)
@bot.command(name="시트테스트", help="연결 확인 시트의 A1에 현재 시간을 기록하고 값을 확인합니다. 예) !시트테스트")
async def 시트테스트(ctx):
    try:
        sh = ws("연결 확인")  # '연결 확인' 시트 핸들러
        sh.update_acell("A1", f"✅ 연결 OK @ {now_kst_str()}")
        val = sh.acell("A1").value
        await ctx.send(f"A1 = {val}")
    except Exception as e:
        await ctx.send(f"❌ 시트 접근 실패: {e}")

# ────────────────────────────────────────────────────────────────────────────────
# 🎮 게임 메뉴
# ────────────────────────────────────────────────────────────────────────────────
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
        user_id = str(interaction.user.id)
        ensure_user_setup(user_id)

        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        if self.custom_id in ["blackjack", "blind_blackjack", "baccarat"]:
            await interaction.response.send_message(
                f"{self.label} - 카드 배분 버튼을 선택해 주세요:",
                view=CardDrawView(self.custom_id),
                ephemeral=False
            )

        elif self.custom_id == "shuffle":
            await interaction.response.send_message(
                "셔플할 게임을 선택해 주세요:",
                view=ShuffleSelectView(),
                ephemeral=False
            )

        elif self.custom_id == "rps":
            choices = {"가위": "✌️", "바위": "✊", "보": "🖐"}
            result = random.choice(list(choices.keys()))
            await interaction.response.send_message(
                f"🎲 가위바위보 결과: {result} {choices[result]}\n{timestamp}",
                ephemeral=False
            )

        elif self.custom_id == "odd_even":
            await interaction.response.send_message(
                "🎲 주사위 개수를 선택해 주세요:",
                view=DiceSelectView(),
                ephemeral=False
            )

        elif self.custom_id == "lotto":
            numbers = sorted(random.sample(range(1, 46), 6))
            await interaction.response.send_message(
                f"🎟 로또 번호 6개:\n{', '.join(map(str, numbers))}\n{timestamp}",
                ephemeral=False
            )

        elif self.custom_id == "slot":
            symbols = ['⭐', '🔔', '🗝️', '👑', '🧀', '🐤']
            result = ''.join(random.choice(symbols) for _ in range(3))
            await interaction.response.send_message(
                f"🎰 슬롯머신 결과:\n{result}\n{timestamp}",
                ephemeral=False
            )

        elif self.custom_id == "shell":
            result = random.choice(['OXX', 'XOX', 'XXO'])
            await interaction.response.send_message(
                f"🎩 야바위 결과:\n{result}\n{timestamp}",
                ephemeral=False
            )

        else:
            await interaction.response.send_message("❌ 지원되지 않는 게임입니다.", ephemeral=False)


# ────────────────────────────────────────────────────────────────────────────────
# 🃏 카드 배분 (블랙잭 / 블라인드 블랙잭 / 바카라)
# ────────────────────────────────────────────────────────────────────────────────
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
        user_id = str(interaction.user.id)
        ensure_user_setup(user_id)

        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        deck_ref = user_decks[user_id][self.game_type]
        idx = user_indices[user_id][self.game_type]

        lines = []
        for _ in range(self.draw_count):
            if not deck_ref:
                lines.append("❌ 카드가 모두 사용되어 셔플이 필요합니다.")
                break

            name = chr(65 + (idx % 26))  # A, B, C ...
            drawn = [deck_ref.pop() for _ in range(1 if self.draw_count == 1 else 2)]
            lines.append(f"{name}: {' '.join(drawn)}")

            idx += 1
            if idx >= 26:
                lines.append("\n[플레이어명을 리셋하여 다시 A부터 표기합니다.]")
                idx = 0

        # 인덱스 갱신
        user_indices[user_id][self.game_type] = idx

        remaining = len(deck_ref)
        response_text = "\n".join(lines)
        response_text += f"\n남은 카드 수: {remaining}장"
        response_text += f"\n{timestamp}"

        await interaction.response.send_message(response_text, ephemeral=False)


# ────────────────────────────────────────────────────────────────────────────────
# 🔄 셔플 선택
# ────────────────────────────────────────────────────────────────────────────────
class ShuffleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.add_item(ShuffleButton("블랙잭 셔플", "blackjack", discord.ButtonStyle.danger))
        self.add_item(ShuffleButton("블라인드 셔플", "blind_blackjack", discord.ButtonStyle.primary))
        self.add_item(ShuffleButton("바카라 셔플", "baccarat", discord.ButtonStyle.success))


class ShuffleButton(discord.ui.Button):
    def __init__(self, label: str, game_key: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"shuffle_{game_key}")
        self.game_key = game_key

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        ensure_user_setup(user_id)

        # 바카라는 6덱(슈) 사용
        if self.game_key == "baccarat":
            user_decks[user_id][self.game_key] = random.sample(deck * 6, len(deck) * 6)
        else:
            user_decks[user_id][self.game_key] = random.sample(deck, len(deck))

        user_indices[user_id][self.game_key] = 0
        await interaction.response.send_message(f"🔄 {self.label} 완료!", ephemeral=False)


# ────────────────────────────────────────────────────────────────────────────────
# 🎲 홀짝용 주사위 선택 (무제한 사용)
# ────────────────────────────────────────────────────────────────────────────────
class DiceSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 무한 사용 가능
        self.add_item(DiceButton("1D6", 1, discord.ButtonStyle.danger))
        self.add_item(DiceButton("2D6", 2, discord.ButtonStyle.primary))
        self.add_item(DiceButton("3D6", 3, discord.ButtonStyle.success))


class DiceButton(discord.ui.Button):
    def __init__(self, label: str, dice_count: int, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"dice_{label}")
        self.dice_count = dice_count

    async def callback(self, interaction: discord.Interaction):
        rolls = [random.randint(1, 6) for _ in range(self.dice_count)]
        odd_even = ["홀" if r % 2 else "짝" for r in rolls]
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        await interaction.response.send_message(
            f"🎲 {self.label} 주사위 값은 {' '.join(map(str, rolls))} → {' '.join(odd_even)}입니다.\n{timestamp}",
            ephemeral=False
        )

@bot.command(name="합계", help="시트 내 포인트 페이지에서 각 진영의 현재 포인트 값을 불러옵니다. 예) !합계")
async def 합계(ctx):
    try:
        sh = ws("포인트")
        v_g2 = sh.acell("G1").value  # 흑운
        v_i2 = sh.acell("I1").value  # 운사
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        await ctx.send(
            f"현재 진영 포인트\n\n흑운: '{v_g1}'\n운사: '{v_i1}'\n{timestamp}"
        )
    except Exception as e:
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        await ctx.send(f"❌ 조회 실패: {e}\n{timestamp}")

def _find_row_by_name(worksheet, name: str) -> int | None:
    # '명단' 시트의 B열에서 정확히 일치하는 첫 행 번호 반환 (없으면 None)
    try:
        colB = worksheet.col_values(2)  # B열 = index 2
        for idx, val in enumerate(colB, start=1):
            if (val or "").strip() == name.strip():
                return idx
        return None
    except Exception:
        return None

def _normalize_items_str(s: str | None) -> str:
    # 콤마로 구분된 아이템 문자열 정규화 (공백 제거, 빈 토큰 제거)
    if not s:
        return ""
    items = [t.strip() for t in s.split(", ") if t.strip()]
    return ", ".join(items)

@bot.command(name="추첨", help="!추첨 숫자 → 시트 내 포인트 페이지의 B5부터 마지막 행까지 이름 중에서 숫자만큼 무작위 추첨합니다. 예) !추첨 3")
async def 추첨(ctx, 숫자: str):
    if not 숫자.isdigit():
        await ctx.send(f"⚠️ 숫자를 입력하세요. 예) `!추첨 3`")
        return

    k = int(숫자)
    if k <= 0:
        await ctx.send(f"⚠️ 1 이상의 숫자를 입력하세요. 예) `!추첨 1`")
        return

    try:
        sh = ws("포인트")
        colB = sh.col_values(2)  # B열 전체
        if len(colB) < 5:
            await ctx.send(f"⚠️ B5 이후 이름 데이터가 없습니다.")
            return

        # B5부터 끝까지, 비어있지 않은 이름만 수집
        candidates = [v.strip() for v in colB[4:] if v and v.strip()]
        total = len(candidates)
        if total == 0:
            await ctx.send(f"⚠️ 추첨 대상이 없습니다. (B5 이후가 비어 있음)")
            return
        if k > total:
            await ctx.send(f"⚠️ 추첨 인원이 대상 수({total}명)를 초과합니다. 더 작은 숫자를 입력하세요.")
            return

        winners = random.sample(candidates, k)
        timestamp = now_kst_str()
        await ctx.send(f"추첨 결과 ({k}명): {', '.join(winners)}\n{timestamp}")

    except Exception as e:
        await ctx.send(f"❌ 추첨 실패: {e}")

# 랜덤 전용 파서 (메시지 문구를 랜덤에 맞춤)
def _parse_names_and_k_for_random(args):
    """
    args: ("이름1","이름2","...","k")
    returns: (names:list[str], k:int) or (None, error_msg)
    """
    if len(args) < 2:
        return None, "⚠️ 최소 1명 이상의 이름과 추첨 인원 수를 입력하세요. 예) `!랜덤 홍길동 김철수 박영희 2`"

    k_str = args[-1]
    if not k_str.isdigit():
        return None, "⚠️ 추첨 인원 수는 양의 정수여야 합니다. 예) `!랜덤 홍길동 김철수 박영희 2`"
    k = int(k_str)
    if k <= 0:
        return None, "⚠️ 추첨 인원 수는 1 이상이어야 합니다."

    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)

    if not names:
        return None, "⚠️ 유효한 이름이 없습니다. 예) `!랜덤 홍길동 김철수 박영희 2`"

    # 동일 이름이 여러 번 들어와도 1명으로 간주(중복 제거, 순서 유지)
    names = list(dict.fromkeys(names))
    return (names, k), None

@bot.command(
    name="랜덤",
    help="!랜덤 이름1 이름2 ... k → 입력한 이름 중 서로 다른 k명을 무작위로 뽑습니다. 예) !랜덤 홍길동 김철수 박영희 2"
)
async def 랜덤(ctx, *args):
    parsed, err = _parse_names_and_k_for_random(args)
    timestamp = now_kst_str()
    if err:
        await ctx.send(f"{err}\n{timestamp}")
        return

    names, k = parsed
    n = len(names)

    # k가 후보 수보다 크면 자동 조정
    adjusted_msg = ""
    if k > n:
        k = n
        adjusted_msg = f"\n(ℹ️ 후보가 {n}명이므로 {n}명으로 추첨 인원을 조정했습니다.)"

    winners = random.sample(names, k)  # 중복 당첨 없음
    await ctx.send(f"랜덤 선택 ({k}명): {', '.join(winners)}{adjusted_msg}\n{timestamp}")

# --- 도우미: 포인트 시트 C열을 기준으로 증감 적용 ---
def _apply_delta_to_points(name: str, delta: int, *, start_row: int = 5) -> tuple[int | None, int | None, int | None, str | None]:
    """
    포인트! B열(B5~)에서 name을 찾아 C열 값을 delta 만큼 증감.
    반환: (row, cur_val, new_val, err)
      - row: 찾은 행 번호 (없으면 None)
      - cur_val/new_val: 현재/변경 후 정수 값 (숫자 아닐 땐 None)
      - err: 오류 메시지 (없으면 None)
    """
    sh = ws("포인트")

    # B열 전체에서 이름 찾기 (B5부터)
    col_b = sh.col_values(2)
    target_row = None
    for idx, v in enumerate(col_b[start_row - 1:], start=start_row):
        if v and v.strip() == name:
            target_row = idx
            break

    if target_row is None:
        return (None, None, None, f"'{name}'을(를) 찾지 못했습니다.")

    # C열 값 읽기/검증
    c_label = f"C{target_row}"
    raw = sh.acell(c_label).value
    s = "" if raw is None else str(raw).strip()
    if s == "":
        cur = 0  # 빈칸은 0으로 간주
    else:
        try:
            cur = int(s)
        except ValueError:
            return (target_row, None, None, f"행 {target_row}의 C열 값이 숫자가 아닙니다: {s}")

    new_val = cur + delta
    sh.update_acell(c_label, new_val)
    return (target_row, cur, new_val, None)

@bot.command(name="추가", help="!추가 이름1 [이름2 ...] 수치 → 포인트 시트 C열(C5~) 값을 수치만큼 증가")
async def 추가(ctx, *args):
    parsed, err = _parse_names_and_amount(args)
    timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    if err:
        await ctx.send(f"{err}\n{timestamp}")
        return

    names, amount = parsed
    delta = amount  # 증가

    ok_lines, fail_lines = [], []
    for 이름 in names:
        row, cur_val, new_val, e = _apply_delta_to_points(이름, delta)
        if e:
            fail_lines.append(f"❌ {e}")
        elif row is None:
            fail_lines.append(f"❌ '{이름}'을(를) 찾지 못했습니다.")
        else:
            ok_lines.append(f"✅ '{이름}' {cur_val} → +{delta} = **{new_val}** (행 {row}, C열)")

    parts = []
    if ok_lines: parts.append("\n".join(ok_lines))
    if fail_lines: parts.append("\n".join(fail_lines))
    parts.append(timestamp)
    await ctx.send("\n".join(parts))


@bot.command(
    name="전체",
    help="!전체 +수치 / -수치 → 포인트 시트 C5부터 마지막 데이터 행까지 숫자 셀에 일괄 증감. 예) !전체 +5, !전체 -3"
)
async def 전체(ctx, 수치: str):
    s = (수치 or "").strip()
    if not (s.startswith("+") or s.startswith("-")):
        await ctx.send("⚠️ 수치는 + 또는 -로 시작해야 합니다. 예) `!전체 +5` 또는 `!전체 -3`")
        return
    try:
        delta = int(s)
    except ValueError:
        await ctx.send("⚠️ 수치는 정수여야 합니다. 예) `!전체 +5` 또는 `!전체 -3`")
        return

    try:
        sh = ws("포인트")

        # C열의 마지막 실제 데이터 행
        col_c = sh.col_values(3)  # C열
        last_row = len(col_c)
        if last_row < 5:
            await ctx.send("⚠️ C5 이후 데이터가 없습니다.")
            return

        rng = f"C5:C{last_row}"
        rows = sh.get(rng)
        new_rows, changed = [], 0

        for r in rows:
            raw = (r[0] if r else "").strip()
            if raw == "":
                new_rows.append([raw])  # 빈칸 유지
                continue
            try:
                cur = int(raw)
                new_rows.append([cur + delta])
                changed += 1
            except ValueError:
                new_rows.append([raw])  # 숫자 아님 → 그대로 둠

        # 일괄 업데이트
        sh.update(rng, new_rows, value_input_option="USER_ENTERED")

        # 최종 수정자 기록 (원하면 위치 조정 가능)
        sh.update_acell("E1", ctx.author.display_name)

        timestamp = now_kst_str()
        await ctx.send(f"✅ 포인트(C열)에 일괄 적용 완료 ({changed}개 변경).\n{timestamp}")

    except Exception as e:
        await ctx.send(f"❌ 일괄 증감 실패: {e}")


@bot.command(name="차감", help="!차감 이름1 [이름2 ...] 수치 → 포인트 시트 C열(C5~) 값을 수치만큼 감소")
async def 차감(ctx, *args):
    parsed, err = _parse_names_and_amount(args)
    timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    if err:
        await ctx.send(f"{err}\n{timestamp}")
        return

    names, amount = parsed
    delta = -amount  # 감소

    ok_lines, fail_lines = [], []
    for 이름 in names:
        row, cur_val, new_val, e = _apply_delta_to_points(이름, delta)
        if e:
            fail_lines.append(f"❌ {e}")
        elif row is None:
            fail_lines.append(f"❌ '{이름}'을(를) 찾지 못했습니다.")
        else:
            ok_lines.append(f"✅ '{이름}' {cur_val} → -{amount} = **{new_val}** (행 {row}, C열)")

    parts = []
    if ok_lines: parts.append("\n".join(ok_lines))
    if fail_lines: parts.append("\n".join(fail_lines))
    parts.append(timestamp)
    await ctx.send("\n".join(parts))

# ✅ 다이스 버튼

class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        # 버튼 제한: 명령어 사용한 사람만
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "이 버튼은 명령어를 사용한 사람만 누를 수 있어요.", ephemeral=True
            )
            return

        roll = random.randint(1, self.sides)
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        await interaction.response.send_message(
            f"{interaction.user.mention}의 **1d{self.sides}** 결과: **{roll}**\n{timestamp}"
        )

class DiceView(View):
    def __init__(self, owner_id: int, timeout: int = None):
        super().__init__(timeout=timeout)
        # 버튼 색: 빨강(위험)=1d6, 파랑(기본)=1d10, 초록(성공)=1d100
        self.add_item(DiceButton(6,   discord.ButtonStyle.danger,  owner_id))
        self.add_item(DiceButton(10,  discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))
        self.message = None

    async def on_timeout(self):
        # timeout=None이면 이 함수는 호출되지 않음
        pass

@bot.command(name="다이스", help="버튼으로 1d6/1d10/1d100을 굴립니다. 예) !다이스")
async def 다이스(ctx):
    view = DiceView(owner_id=ctx.author.id)
    msg = await ctx.send(f"{ctx.author.mention} 굴릴 주사위를 선택하세요:", view=view)
    view.message = msg


bot.run(DISCORD_TOKEN)
