# 诊断报告 · 自愈逾限

- 台账：`x.xlsx`
- 失败步骤：**解析台账**（`parse` → 工具 `run_parse`）
- 错误码：`ASSERT_FAIL`
- 错误说明：2 项断言未过
- 已尝试：首轮 + 1 次自愈重试（上限 1）

## 自愈过程

- 结论：`repaired`
- 已应用规则：['discipline_alias_map']
- 记录：`（未落盘）`
- 提交的读表口径：`{"discipline_alias": {"化学": "Chemistry", "植物与动物学": "Plant & Animal Science", "微生物学": "Microbiology", "工程学": "Engineering", "材料科学": "Materials Science", "数学": "Mathematics", "环境生态学": "Environment/Ecology", "生物学与生物化学": "Biology & Biochemistry", "药理学与毒理学": "Pharmacology & Toxicology", "地球科学": "Geosciences", "农业科学": "Agricultural Sciences", "计算机科学": "Computer Science", "临床医学": "Clinical Medicine", "分子生物学与遗传学": "Molecular Biology & Genetics", "物理学": "Physics", "社会科学": "Social Sciences, general", "多学科": "Multidisciplinary", "神经系统科学与行为学": "Neuroscience & Behavior", "空间科学": "Space Science", "免疫学": "Immunology", "精神病学与心理学": "Psychiatry/Psychology", "经济与商业": "Economics & Business", "Social Sciences": "Social Sciences, general", "Environment / Ecology": "Environment/Ecology", "Environment & Ecology": "Environment/Ecology", "Plant and Animal Science": "Plant & Animal Science", "Neuroscience and Behavior": "Neuroscience & Behavior", "Biology and Biochemistry": "Biology & Biochemistry", "Pharmacology and Toxicology": "Pharmacology & Toxicology", "Molecular Biology and Genetics": "Molecular Biology & Genetics", "Psychiatry / Psychology": "Psychiatry/Psychology", "Business & Economics": "Economics & Business", "Business and Economics": "Economics & Business"}}`

### 本次失败实况

- 202607 期，「总被引」，期望 22、实际 21，缺 Chemistry，认不出来的名字：「某某新学科」。

### 需人工：表头行偏移声明（header_offset）

- 原因：未确认规则类型（R-24）
- 依据：WH-DOC-04 §6.5「多级/合并表头」——须馆员声明表头行号，机器不猜
- **怎么核对**：打开「总被引」，数清表头实际落在第几行（0 起数：Excel 第 1 行 = 0）。把 {工作表名: 行号} 填进本规则的 declared 后再重跑。本次期望 22、实际读到 21。

> 规则库口径：命中「表头错位」形态。机器不猜表头行号（猜错会整体错位且不报错）， 请馆员把 {工作表名: 表头行号} 填进本规则的 declared 后再重跑。

## 明细

```json
{
  "code": "ASSERT_FAIL",
  "message": "2 项断言未过",
  "period": "202607",
  "fails": [
    "宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])"
  ],
  "diagnostics": {
    "unmatched_names": {
      "total_cites": [
        "某某新学科"
      ]
    }
  }
}
```

## 台账里认不出来的学科名

把下面这些名字与规范名单对上，或补进 `repair_rules.yaml` 的别名表：

- `total_cites` 首列：['某某新学科']

## 处置

1. 该运行已停止，**未继续后续步骤**，不产出报告初稿；
2. 请人工核对台账对应工作表/期次列，修正后重跑（重跑会新建运行，本记录保留）；
3. 若属新出现的脏例，请在 `src/agent/rules/repair_rules.yaml` 补规则并经馆员确认。

## 未通过的断言

- 宽表 total_cites 学科数=22 (实际 21，缺 ['Chemistry'])

---

> 本报告由 `src/agent/flow.py` 自动生成，未经过模型加工。