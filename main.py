import csv
import random
from collections import Counter, defaultdict
from pathlib import Path


# =========================
# ファイルや設定
# =========================

BASE_DIR = Path(__file__).parent

DATA_FILE = BASE_DIR / "data" / "responses.csv"
MANUAL_FILE = BASE_DIR / "data" / "manual_assignments.csv"

OUTPUT_DIR = BASE_DIR / "output"

PRACTICE_RESULT_FILE = (
    OUTPUT_DIR / "assignment_results.csv"
)

EVENT_RESULT_FILE = (
    OUTPUT_DIR / "event_results.csv"
)


# Googleフォームの列名
NAME_COLUMN = "お名前"

LINE_NAME_COLUMN = (
    "LINE名（正確にお願いします）"
)

SCHEDULE_COLUMN = (
    "参加したい練習日程(一部10時からの枠があります)"
)

EVENT_COLUMN = "参加したいイベント"


# 幹部1人分を除いた一般応募者の定員
VENUE_CAPACITIES = {
    "成城": 9,
    "高島平": 9,
    "学芸大学": 17,
}


# 開発中は毎回同じ抽選結果にする
RANDOM_SEED = 42


# =========================
# 共通処理
# =========================

def split_choices(text):
    """
    Googleフォームの複数選択回答を、
    1件ずつのリストに分解する。
    """

    if not text:
        return []

    return [
        choice.strip()
        for choice in text.split(",")
        if choice.strip()
    ]


def get_capacity(schedule):
    """
    日程名から会場を判定し、
    一般応募者の定員を返す。
    """

    for venue, capacity in VENUE_CAPACITIES.items():
        if venue in schedule:
            return capacity

    raise ValueError(
        f"会場を判定できませんでした：{schedule}"
    )


def format_participant(
    name,
    participant_line_names,
):
    """
    本名とLINE名を表示用の文字列にする。
    """

    line_name = participant_line_names.get(
        name,
        "未登録",
    )

    return f"{name}（LINE名：{line_name}）"


# =========================
# Googleフォーム回答の読み込み
# =========================

def load_responses():
    """
    Googleフォーム回答CSVを読み込む。

    戻り値：
    ・日程ごとの練習応募者
    ・イベントごとの応募者
    ・本名とLINE名の対応表
    """

    schedule_applicants = defaultdict(list)
    event_applicants = defaultdict(list)

    participant_line_names = {}

    with DATA_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for response in reader:
            name = (
                response.get(NAME_COLUMN) or ""
            ).strip()

            line_name = (
                response.get(LINE_NAME_COLUMN) or ""
            ).strip()

            schedules_text = (
                response.get(SCHEDULE_COLUMN) or ""
            ).strip()

            events_text = (
                response.get(EVENT_COLUMN) or ""
            ).strip()

            # 本名が空欄なら処理しない
            if not name:
                continue

            # LINE名が空欄ならエラー
            if not line_name:
                raise ValueError(
                    f"{name}さんのLINE名が空欄です。"
                )

            # 同じ本名で異なるLINE名が登録されていたらエラー
            if name in participant_line_names:
                registered_line_name = (
                    participant_line_names[name]
                )

                if registered_line_name != line_name:
                    raise ValueError(
                        f"{name}さんについて、"
                        "異なるLINE名が登録されています。"
                        f"「{registered_line_name}」と"
                        f"「{line_name}」"
                    )

            participant_line_names[name] = line_name

            # 練習日程を日程ごとに整理する
            for schedule in split_choices(
                schedules_text
            ):
                schedule_applicants[schedule].append(
                    name
                )

            # イベントをイベントごとに整理する
            for event in split_choices(events_text):
                event_applicants[event].append(name)

    return (
        schedule_applicants,
        event_applicants,
        participant_line_names,
    )


# =========================
# 手動確定ファイルの読み込み
# =========================

def load_manual_assignments():
    """
    手動で確定する練習参加者を
    CSVから読み込む。
    """

    manual_assignments = defaultdict(list)

    with MANUAL_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            schedule = (
                row.get("schedule") or ""
            ).strip()

            name = (
                row.get("name") or ""
            ).strip()

            # 完全な空行は無視する
            if not schedule and not name:
                continue

            # 片方だけ空欄ならエラー
            if not schedule or not name:
                raise ValueError(
                    "manual_assignments.csvに、"
                    "日程または名前が空欄の行があります。"
                )

            manual_assignments[schedule].append(
                name
            )

    return manual_assignments


# =========================
# 手動確定内容の確認
# =========================

def validate_manual_assignments(
    schedule_applicants,
    manual_assignments,
):
    """
    手動確定の内容に間違いがないか確認する。
    """

    for schedule, names in (
        manual_assignments.items()
    ):
        # 日程が応募データに存在するか
        if schedule not in schedule_applicants:
            raise ValueError(
                "手動確定の日程が"
                "応募データにありません："
                f"{schedule}"
            )

        # 同じ日程で同じ人が重複していないか
        if len(names) != len(set(names)):
            raise ValueError(
                "同じ人が重複して"
                "手動確定されています："
                f"{schedule}"
            )

        applicants = schedule_applicants[schedule]

        # その日程に応募した人か
        for name in names:
            if name not in applicants:
                raise ValueError(
                    f"{name}さんは"
                    f"「{schedule}」に"
                    "応募していません。"
                )

        capacity = get_capacity(schedule)

        # 手動確定者だけで定員超過していないか
        if len(names) > capacity:
            raise ValueError(
                "手動確定者が定員を"
                "超えています："
                f"{schedule}"
            )


# =========================
# 練習結果のCSV保存
# =========================

def save_practice_results(
    schedule_applicants,
    selected_participants,
    rejected_participants,
    manual_assignments,
    participation_counts,
    participant_line_names,
):
    """
    練習の振り分け結果を
    CSVファイルとして保存する。
    """

    OUTPUT_DIR.mkdir(exist_ok=True)

    with PRACTICE_RESULT_FILE.open(
        mode="w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        fieldnames = [
            "日程",
            "結果",
            "本名",
            "LINE名",
            "選出方法",
            "最終練習参加回数",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for schedule in schedule_applicants:
            manual_names = set(
                manual_assignments.get(
                    schedule,
                    [],
                )
            )

            # 参加者を保存
            for name in selected_participants[
                schedule
            ]:
                if name in manual_names:
                    selection_method = "手動確定"
                else:
                    selection_method = "自動選出"

                writer.writerow(
                    {
                        "日程": schedule,
                        "結果": "参加",
                        "本名": name,
                        "LINE名": (
                            participant_line_names[name]
                        ),
                        "選出方法": selection_method,
                        "最終練習参加回数": (
                            participation_counts[name]
                        ),
                    }
                )

            # 落選者を保存
            for name in rejected_participants[
                schedule
            ]:
                writer.writerow(
                    {
                        "日程": schedule,
                        "結果": "落選",
                        "本名": name,
                        "LINE名": (
                            participant_line_names[name]
                        ),
                        "選出方法": "自動抽選",
                        "最終練習参加回数": (
                            participation_counts[name]
                        ),
                    }
                )


# =========================
# イベント結果のCSV保存
# =========================

def save_event_results(
    event_applicants,
    participant_line_names,
):
    """
    イベント参加者をCSVに保存する。

    イベントは定員・抽選なしで、
    応募者全員を参加とする。
    """

    OUTPUT_DIR.mkdir(exist_ok=True)

    with EVENT_RESULT_FILE.open(
        mode="w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        fieldnames = [
            "イベント",
            "参加者数",
            "本名",
            "LINE名",
            "結果",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for event, participants in (
            event_applicants.items()
        ):
            participant_count = len(participants)

            for name in participants:
                writer.writerow(
                    {
                        "イベント": event,
                        "参加者数": participant_count,
                        "本名": name,
                        "LINE名": (
                            participant_line_names[name]
                        ),
                        "結果": "参加",
                    }
                )


# =========================
# メイン処理
# =========================

random_generator = random.Random(RANDOM_SEED)


# Googleフォーム回答を読み込む
(
    schedule_applicants,
    event_applicants,
    participant_line_names,
) = load_responses()


# 手動確定ファイルを読み込む
manual_assignments = load_manual_assignments()


# 手動確定内容をチェックする
validate_manual_assignments(
    schedule_applicants,
    manual_assignments,
)


# 日程ごとの練習参加者
selected_participants = defaultdict(list)

# 日程ごとの練習落選者
rejected_participants = defaultdict(list)

# 人ごとの練習参加回数
participation_counts = Counter()

# 定員超過の日程
pending_schedules = {}


# =========================
# 定員内の日程を確定
# =========================

for schedule, applicants in (
    schedule_applicants.items()
):
    capacity = get_capacity(schedule)

    if len(applicants) <= capacity:
        selected_participants[schedule] = (
            applicants.copy()
        )

        for name in applicants:
            participation_counts[name] += 1

    else:
        pending_schedules[schedule] = (
            applicants.copy()
        )


# =========================
# 手動確定者を先に登録
# =========================

for schedule in pending_schedules:
    fixed_participants = (
        manual_assignments.get(
            schedule,
            [],
        )
    )

    selected_participants[schedule].extend(
        fixed_participants
    )

    for name in fixed_participants:
        participation_counts[name] += 1


# =========================
# 残った練習枠を公平に抽選
# =========================

for schedule, applicants in (
    pending_schedules.items()
):
    capacity = get_capacity(schedule)

    fixed_participants = (
        manual_assignments.get(
            schedule,
            [],
        )
    )

    fixed_participant_set = set(
        fixed_participants
    )

    remaining_capacity = (
        capacity - len(fixed_participants)
    )

    # 手動確定者を抽選対象から除く
    lottery_candidates = [
        name
        for name in applicants
        if name not in fixed_participant_set
    ]

    # 同じ参加回数の人の順番をランダム化
    random_generator.shuffle(
        lottery_candidates
    )

    # 現在の参加回数が少ない順に並べる
    ranked_candidates = sorted(
        lottery_candidates,
        key=lambda name: participation_counts[name],
    )

    winners = ranked_candidates[
        :remaining_capacity
    ]

    losers = ranked_candidates[
        remaining_capacity:
    ]

    selected_participants[schedule].extend(
        winners
    )

    rejected_participants[schedule] = losers

    for name in winners:
        participation_counts[name] += 1


# =========================
# 練習結果をターミナル表示
# =========================

print("練習の振り分け結果")
print("====================")

if not schedule_applicants:
    print("練習への応募はありません。")

for schedule in schedule_applicants:
    participants = selected_participants[
        schedule
    ]

    rejected = rejected_participants[
        schedule
    ]

    manual_names = set(
        manual_assignments.get(
            schedule,
            [],
        )
    )

    print()
    print(schedule)
    print(f"定員：{get_capacity(schedule)}人")

    print(
        f"応募者数："
        f"{len(schedule_applicants[schedule])}人"
    )

    print("【参加者】")

    for name in participants:
        participant_text = format_participant(
            name,
            participant_line_names,
        )

        if name in manual_names:
            print(
                f"・{participant_text}"
                "（手動確定）"
            )
        else:
            print(f"・{participant_text}")

    if rejected:
        print("【落選者】")

        for name in rejected:
            participant_text = format_participant(
                name,
                participant_line_names,
            )

            print(f"・{participant_text}")


print()
print("最終的な練習参加回数")
print("====================")

if not participation_counts:
    print("練習参加者はいません。")

for name, count in sorted(
    participation_counts.items()
):
    participant_text = format_participant(
        name,
        participant_line_names,
    )

    print(f"{participant_text}：{count}回")


# =========================
# イベント結果をターミナル表示
# =========================

print()
print("イベント参加希望者")
print("====================")

if not event_applicants:
    print("イベントへの応募はありません。")

for event, participants in (
    event_applicants.items()
):
    print()
    print(event)
    print(f"参加者数：{len(participants)}人")
    print("【参加者・全員参加】")

    for name in participants:
        participant_text = format_participant(
            name,
            participant_line_names,
        )

        print(f"・{participant_text}")


# =========================
# CSVファイルとして保存
# =========================

save_practice_results(
    schedule_applicants,
    selected_participants,
    rejected_participants,
    manual_assignments,
    participation_counts,
    participant_line_names,
)

save_event_results(
    event_applicants,
    participant_line_names,
)


print()
print(
    "練習結果を保存しました："
    f"{PRACTICE_RESULT_FILE}"
)

print(
    "イベント結果を保存しました："
    f"{EVENT_RESULT_FILE}"
)