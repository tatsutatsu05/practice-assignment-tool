import csv
import random
from collections import Counter, defaultdict, deque
from pathlib import Path


BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "responses.csv"
MANUAL_FILE = BASE_DIR / "data" / "manual_assignments.csv"
OUTPUT_DIR = BASE_DIR / "output"
PRACTICE_RESULT_FILE = OUTPUT_DIR / "assignment_results.csv"
EVENT_RESULT_FILE = OUTPUT_DIR / "event_results.csv"

NAME_COLUMN = "お名前"
LINE_NAME_COLUMN = "LINE名（正確にお願いします）"
SCHEDULE_COLUMN = "参加したい練習日程(開始時刻に注意してください)"
EVENT_COLUMN = "参加したいイベント"

VENUE_CAPACITIES = {
    "成城": 9,
    "高島平": 9,
    "学芸": 17,
}

RANDOM_SEED = 42
TIE_BREAK_RANGE = 1000


def split_choices(text):
    return [
        item.strip()
        for item in (text or "").split(",")
        if item.strip()
    ]


def get_capacity(schedule):
    for venue, capacity in VENUE_CAPACITIES.items():
        if venue in schedule:
            return capacity
    raise ValueError(f"会場を判定できませんでした：{schedule}")


def format_person(name, line_names):
    return f"{name}（LINE名：{line_names[name]}）"


def load_responses():
    schedule_applicants = defaultdict(list)
    event_applicants = defaultdict(list)
    line_names = {}
    schedule_seen = defaultdict(set)
    event_seen = defaultdict(set)

    with DATA_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        required = {
            NAME_COLUMN,
            LINE_NAME_COLUMN,
            SCHEDULE_COLUMN,
            EVENT_COLUMN,
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "responses.csvに必要な列がありません："
                + ", ".join(sorted(missing))
            )

        for row in reader:
            name = (row.get(NAME_COLUMN) or "").strip()
            line_name = (row.get(LINE_NAME_COLUMN) or "").strip()

            if not name:
                continue
            if not line_name:
                raise ValueError(f"{name}さんのLINE名が空欄です。")

            if name in line_names and line_names[name] != line_name:
                raise ValueError(
                    f"{name}さんに異なるLINE名があります："
                    f"「{line_names[name]}」「{line_name}」"
                )
            line_names[name] = line_name

            for schedule in split_choices(row.get(SCHEDULE_COLUMN)):
                if name not in schedule_seen[schedule]:
                    schedule_applicants[schedule].append(name)
                    schedule_seen[schedule].add(name)

            for event in split_choices(row.get(EVENT_COLUMN)):
                if name not in event_seen[event]:
                    event_applicants[event].append(name)
                    event_seen[event].add(name)

    return schedule_applicants, event_applicants, line_names


def load_manual_assignments():
    manual = defaultdict(list)

    if not MANUAL_FILE.exists():
        return manual

    with MANUAL_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if set(reader.fieldnames or []) != {"schedule", "name"}:
            raise ValueError(
                "manual_assignments.csvの見出しは"
                "「schedule,name」にしてください。"
            )

        for row in reader:
            schedule = (row.get("schedule") or "").strip()
            name = (row.get("name") or "").strip()

            if not schedule and not name:
                continue
            if not schedule or not name:
                raise ValueError(
                    "manual_assignments.csvに空欄の項目があります。"
                )

            manual[schedule].append(name)

    return manual


def validate_manual(schedule_applicants, manual):
    for schedule, names in manual.items():
        if schedule not in schedule_applicants:
            raise ValueError(
                f"手動確定の日程が応募データにありません：{schedule}"
            )
        if len(names) != len(set(names)):
            raise ValueError(
                f"同じ人が重複して手動確定されています：{schedule}"
            )

        applicants = set(schedule_applicants[schedule])
        for name in names:
            if name not in applicants:
                raise ValueError(
                    f"{name}さんは「{schedule}」に応募していません。"
                )

        if len(names) > get_capacity(schedule):
            raise ValueError(
                f"手動確定者が定員を超えています：{schedule}"
            )


class Edge:
    def __init__(self, to, reverse_index, capacity, cost):
        self.to = to
        self.reverse_index = reverse_index
        self.capacity = capacity
        self.cost = cost


class MinCostMaxFlow:
    def __init__(self, node_count):
        self.graph = [[] for _ in range(node_count)]

    def add_edge(self, source, target, capacity, cost):
        forward = Edge(
            target,
            len(self.graph[target]),
            capacity,
            cost,
        )
        backward = Edge(
            source,
            len(self.graph[source]),
            0,
            -cost,
        )
        self.graph[source].append(forward)
        self.graph[target].append(backward)
        return forward

    def run(self, source, sink, required_flow):
        flow = 0
        cost = 0
        node_count = len(self.graph)

        while flow < required_flow:
            distance = [None] * node_count
            previous_node = [-1] * node_count
            previous_edge = [-1] * node_count
            in_queue = [False] * node_count

            distance[source] = 0
            queue = deque([source])
            in_queue[source] = True

            while queue:
                node = queue.popleft()
                in_queue[node] = False

                for edge_index, edge in enumerate(self.graph[node]):
                    if edge.capacity <= 0:
                        continue

                    new_distance = distance[node] + edge.cost
                    if (
                        distance[edge.to] is None
                        or new_distance < distance[edge.to]
                    ):
                        distance[edge.to] = new_distance
                        previous_node[edge.to] = node
                        previous_edge[edge.to] = edge_index

                        if not in_queue[edge.to]:
                            queue.append(edge.to)
                            in_queue[edge.to] = True

            if previous_node[sink] == -1:
                break

            added = required_flow - flow
            node = sink

            while node != source:
                prev = previous_node[node]
                edge = self.graph[prev][previous_edge[node]]
                added = min(added, edge.capacity)
                node = prev

            node = sink

            while node != source:
                prev = previous_node[node]
                edge = self.graph[prev][previous_edge[node]]
                edge.capacity -= added
                self.graph[node][edge.reverse_index].capacity += added
                node = prev

            flow += added
            cost += distance[sink] * added

        return flow, cost


def optimize_assignments(schedule_applicants, manual):
    selected = defaultdict(list)
    rejected = defaultdict(list)
    counts = Counter()
    methods = {}
    oversubscribed = {}

    # 0回の人も公平性評価に含める
    for applicants in schedule_applicants.values():
        for name in applicants:
            counts[name] = 0

    # 定員内の日程は全員参加として先に確定
    for schedule, applicants in schedule_applicants.items():
        manual_names = set(manual.get(schedule, []))

        if len(applicants) <= get_capacity(schedule):
            selected[schedule] = applicants.copy()

            for name in applicants:
                counts[name] += 1
                methods[(schedule, name)] = (
                    "手動確定"
                    if name in manual_names
                    else "定員内確定"
                )
        else:
            oversubscribed[schedule] = applicants.copy()

    # 定員超過日程の手動確定者を固定
    for schedule in oversubscribed:
        for name in manual.get(schedule, []):
            selected[schedule].append(name)
            counts[name] += 1
            methods[(schedule, name)] = "手動確定"

    remaining_capacity = {}
    candidate_schedules = defaultdict(list)

    # 定員超過の全日程を、まとめて最適化する準備
    for schedule, applicants in oversubscribed.items():
        fixed = set(manual.get(schedule, []))
        remaining_capacity[schedule] = (
            get_capacity(schedule) - len(fixed)
        )

        if remaining_capacity[schedule] <= 0:
            continue

        for name in applicants:
            if name not in fixed:
                candidate_schedules[name].append(schedule)

    required_flow = sum(remaining_capacity.values())

    if required_flow:
        people = sorted(candidate_schedules)
        schedules = sorted(remaining_capacity)

        source = 0
        person_start = 1
        schedule_start = person_start + len(people)
        sink = schedule_start + len(schedules)

        person_node = {
            name: person_start + index
            for index, name in enumerate(people)
        }
        schedule_node = {
            schedule: schedule_start + index
            for index, schedule in enumerate(schedules)
        }

        solver = MinCostMaxFlow(sink + 1)

        # 公平性を抽選用乱数より必ず優先させる
        fairness_base = required_flow + 1
        tie_scale = required_flow * TIE_BREAK_RANGE + 1

        # 1人の1回目、2回目、3回目…ほど費用を大きくする。
        # これにより、まず参加0回の人を減らし、
        # 次に1回の人を減らす、という順で全体を公平化する。
        for name in people:
            current_count = counts[name]
            possible_count = len(candidate_schedules[name])

            for extra_index in range(possible_count):
                level = current_count + extra_index
                fairness_cost = fairness_base ** level

                solver.add_edge(
                    source,
                    person_node[name],
                    1,
                    fairness_cost * tie_scale,
                )

        random_generator = random.Random(RANDOM_SEED)
        pairs = [
            (name, schedule)
            for name, schedules_for_name in candidate_schedules.items()
            for schedule in schedules_for_name
        ]
        random_generator.shuffle(pairs)

        assignment_edges = {}

        for name, schedule in pairs:
            edge = solver.add_edge(
                person_node[name],
                schedule_node[schedule],
                1,
                random_generator.randrange(TIE_BREAK_RANGE),
            )
            assignment_edges[(name, schedule)] = edge

        for schedule in schedules:
            solver.add_edge(
                schedule_node[schedule],
                sink,
                remaining_capacity[schedule],
                0,
            )

        actual_flow, _ = solver.run(
            source,
            sink,
            required_flow,
        )

        if actual_flow != required_flow:
            raise RuntimeError(
                "全枠を割り当てられませんでした。"
                "応募データを確認してください。"
            )

        for schedule, applicants in oversubscribed.items():
            selected_set = set(selected[schedule])

            for name in applicants:
                edge = assignment_edges.get((name, schedule))

                if edge is not None and edge.capacity == 0:
                    selected[schedule].append(name)
                    selected_set.add(name)
                    counts[name] += 1
                    methods[(schedule, name)] = "全体最適化"

            rejected[schedule] = [
                name
                for name in applicants
                if name not in selected_set
            ]

    for schedule, applicants in oversubscribed.items():
        if schedule not in rejected:
            selected_set = set(selected[schedule])
            rejected[schedule] = [
                name
                for name in applicants
                if name not in selected_set
            ]

    return selected, rejected, counts, methods


def validate_results(
    schedule_applicants,
    selected,
    rejected,
    manual,
    counts,
):
    recalculated = Counter()

    for applicants in schedule_applicants.values():
        for name in applicants:
            recalculated[name] = 0

    for schedule, applicants in schedule_applicants.items():
        selected_names = selected[schedule]
        rejected_names = rejected[schedule]

        if len(selected_names) > get_capacity(schedule):
            raise RuntimeError(
                f"定員超過が発生しています：{schedule}"
            )
        if set(selected_names) & set(rejected_names):
            raise RuntimeError(
                f"参加者と落選者が重複しています：{schedule}"
            )
        if (
            set(selected_names) | set(rejected_names)
            != set(applicants)
        ):
            raise RuntimeError(
                f"応募者と結果が一致しません：{schedule}"
            )
        if not set(manual.get(schedule, [])) <= set(selected_names):
            raise RuntimeError(
                f"手動確定者が参加者にいません：{schedule}"
            )

        for name in selected_names:
            recalculated[name] += 1

    if recalculated != counts:
        raise RuntimeError("参加回数の集計が一致しません。")


def save_practice_results(
    schedule_applicants,
    selected,
    rejected,
    counts,
    line_names,
    methods,
):
    OUTPUT_DIR.mkdir(exist_ok=True)

    with PRACTICE_RESULT_FILE.open(
        "w",
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
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for schedule in schedule_applicants:
            for name in selected[schedule]:
                writer.writerow(
                    {
                        "日程": schedule,
                        "結果": "参加",
                        "本名": name,
                        "LINE名": line_names[name],
                        "選出方法": methods[(schedule, name)],
                        "最終練習参加回数": counts[name],
                    }
                )

            for name in rejected[schedule]:
                writer.writerow(
                    {
                        "日程": schedule,
                        "結果": "落選",
                        "本名": name,
                        "LINE名": line_names[name],
                        "選出方法": "全体最適化で未選出",
                        "最終練習参加回数": counts[name],
                    }
                )


def save_event_results(event_applicants, line_names):
    OUTPUT_DIR.mkdir(exist_ok=True)

    with EVENT_RESULT_FILE.open(
        "w",
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
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for event, participants in event_applicants.items():
            for name in participants:
                writer.writerow(
                    {
                        "イベント": event,
                        "参加者数": len(participants),
                        "本名": name,
                        "LINE名": line_names[name],
                        "結果": "参加",
                    }
                )


def main():
    (
        schedule_applicants,
        event_applicants,
        line_names,
    ) = load_responses()

    manual = load_manual_assignments()
    validate_manual(schedule_applicants, manual)

    selected, rejected, counts, methods = (
        optimize_assignments(
            schedule_applicants,
            manual,
        )
    )

    validate_results(
        schedule_applicants,
        selected,
        rejected,
        manual,
        counts,
    )

    print("練習の振り分け結果")
    print("====================")

    if not schedule_applicants:
        print("練習への応募はありません。")

    for schedule in schedule_applicants:
        print()
        print(schedule)
        print(f"定員：{get_capacity(schedule)}人")
        print(f"応募者数：{len(schedule_applicants[schedule])}人")
        print("【参加者】")

        for name in selected[schedule]:
            print(
                f"・{format_person(name, line_names)}"
                f"（{methods[(schedule, name)]}）"
            )

        if rejected[schedule]:
            print("【落選者】")
            for name in rejected[schedule]:
                print(f"・{format_person(name, line_names)}")

    print()
    print("最終的な練習参加回数")
    print("====================")

    for name, count in sorted(counts.items()):
        print(f"{format_person(name, line_names)}：{count}回")

    if counts:
        values = list(counts.values())
        print()
        print(
            f"参加回数の最大差："
            f"{max(values) - min(values)}回"
        )

    print()
    print("イベント参加希望者")
    print("====================")

    if not event_applicants:
        print("イベントへの応募はありません。")

    for event, participants in event_applicants.items():
        print()
        print(event)
        print(f"参加者数：{len(participants)}人")
        print("【参加者・全員参加】")

        for name in participants:
            print(f"・{format_person(name, line_names)}")

    save_practice_results(
        schedule_applicants,
        selected,
        rejected,
        counts,
        line_names,
        methods,
    )
    save_event_results(event_applicants, line_names)

    print()
    print(f"練習結果を保存しました：{PRACTICE_RESULT_FILE}")
    print(f"イベント結果を保存しました：{EVENT_RESULT_FILE}")


if __name__ == "__main__":
    main()