"""profile 模块演示脚本。

按「建档 → 翻译为标签向量 → 生成个性化评价框架 → 下游模块消费」的链路，
直观展示 profile 模块的输入输出以及各模块间的调用方式。
运行方式：``python scripts/demo_profile.py``
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaleido.profile.models.student import CreateStudentRequest, StudentAttributesInput
from kaleido.profile.service import ProfileService

# 四个典型样例，覆盖不同障碍类型、程度与认知等级
SAMPLES = [
    {
        "name": "小明",
        "attributes": {
            "disabilities": ["visual"],
            "severity": "moderate",
            "cognitive_level": "primary_3",
            "sensory_preference": None,
            "rehab_goals": ["language", "cognitive"],
            "learning_pace": "slow",
        },
    },
    {
        "name": "小红",
        "attributes": {
            "disabilities": ["hearing"],
            "severity": "mild",
            "cognitive_level": "primary_5",
            "sensory_preference": None,
            "rehab_goals": ["social"],
            "learning_pace": "medium",
        },
    },
    {
        "name": "小刚",
        "attributes": {
            "disabilities": ["intellectual"],
            "severity": "severe",
            "cognitive_level": "primary_3",
            "sensory_preference": None,
            "rehab_goals": ["sensory_integration"],
            "learning_pace": "slow",
        },
    },
    {
        "name": "小美",
        "attributes": {
            "disabilities": ["autism"],
            "severity": "moderate",
            "cognitive_level": "preschool",
            "sensory_preference": None,
            "rehab_goals": ["social"],
            "learning_pace": "slow",
        },
    },
]


def line(title: str) -> None:
    """打印分节标题。"""
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def describe(profile: dict) -> None:
    """打印单个学生的标签向量与生成的评价框架。"""
    attrs = profile["attributes"]
    fw = profile["framework"]
    print(f"[学生] {profile['name']}  ({profile['profile_id']})")
    print("  ── 原始录入被翻译成的标签向量 ──")
    print(f"     障碍类型      : {', '.join(attrs['disabilities'])}")
    print(f"     障碍程度      : {attrs['severity']}")
    print(f"     认知等级      : {attrs['cognitive_level']}")
    print(f"     感官偏好      : {attrs['sensory_preference']}  (由主障碍类型规则推导)")
    print(f"     康复目标      : {', '.join(attrs['rehab_goals']) or '无'}")
    print(f"     学习节奏      : {attrs['learning_pace']}")
    print(f"     适配约束      : {attrs['adaptation_constraints']}")
    print(f"     Prompt 模板键 : {attrs['prompt_template_key']}")
    print("  ── 生成的评价框架（公共标准） ──")
    print(f"     评价维度权重  : {fw['weights']}")
    print(f"     指标数量      : {len(fw['indicators'])}")
    for indicator in fw["indicators"]:
        names = "、".join(obs["name"] for obs in indicator["observations"])
        print(f"       - [{indicator['dimension']}] {indicator['name']}: {names}")


def demo_external_usage(profile: dict) -> None:
    """演示下游模块（forge/match/loop）如何消费这条画像。"""
    attrs = profile["attributes"]
    fw = profile["framework"]
    print(f"\n→ 外部模块拿到「{profile['name']}」这条画像后各自怎么用：")

    print("  [kaleido-forge 生成层]")
    print(f"    依据 adaptation_constraints={attrs['adaptation_constraints']}")
    print(f"    选用 prompt_template_key={attrs['prompt_template_key']} 生成资源")

    print("  [kaleido-match 匹配层]")
    print(f"    按 disabilities={attrs['disabilities']} + cognitive_level={attrs['cognitive_level']} 过滤资源库")
    if "hearing" in attrs["disabilities"] and attrs["sensory_preference"] == "visual_first":
        print("    硬规则：排除无字幕的纯音频资源")

    print("  [kaleido-loop 反馈层]")
    checklist = []
    for indicator in fw["indicators"]:
        for obs in indicator["observations"]:
            checklist.append(f"{obs['name']}({obs['frequency']})")
    print(f"    采集清单共 {len(checklist)} 项，例如：{'、'.join(checklist[:3])} ...")


def demo_preview(service: ProfileService) -> None:
    """演示属性变化如何即时影响评价框架（不落库）。"""
    line("B. 只预览：改一个属性，评价框架立刻变化（不落库）")
    mild = service.preview_framework(
        StudentAttributesInput(
            disabilities=["intellectual"],
            severity="mild",
            cognitive_level="primary_5",
            rehab_goals=["cognitive"],
            learning_pace="medium",
        )
    )
    severe = service.preview_framework(
        StudentAttributesInput(
            disabilities=["intellectual"],
            severity="severe",
            cognitive_level="primary_5",
            rehab_goals=["cognitive"],
            learning_pace="medium",
        )
    )
    print(f"轻度 指标数={len(mild['framework']['indicators'])} 权重={mild['framework']['weights']}")
    print(f"重度 指标数={len(severe['framework']['indicators'])} 权重={severe['framework']['weights']}")
    first = severe["framework"]["indicators"][0]["observations"][0]
    print(f"重度时观测点频率被提升为: {first['frequency']}")
    print(f"重度时评分标准等级数被压缩为: {len(first['rubrics'])}")


def main() -> None:
    """依次演示建档、框架预览、下游消费与列表查询。"""
    service = ProfileService()

    line("A. 建立学生：录入 → 翻译标签向量 → 生成评价框架")
    created = []
    for index, sample in enumerate(SAMPLES, start=1):
        request = CreateStudentRequest(
            client_request_id=f"demo-req-{index}",
            name=sample["name"],
            attributes=StudentAttributesInput(**sample["attributes"]),
        )
        try:
            profile = service.create_student(request)
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {sample['name']}: {exc}")
            continue
        created.append(profile)
        describe(profile)

    line("C. 下游模块消费画像（演示模块间调用）")
    for profile in created:
        demo_external_usage(profile)

    demo_preview(service)

    line("D. 列表查询（match 层的雏形）")
    listed = service.list_students()
    print(f"共 {listed['total']} 名学生：")
    for item in listed["items"]:
        print(f"  {item['profile_id']}  {item['name']}  {'/'.join(item['disabilities'])}/{item['severity']}")


if __name__ == "__main__":
    main()
