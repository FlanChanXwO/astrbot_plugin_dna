# 本地离线渲染对比：密函（legacy draw_mh_simple vs rewrite render_mh）

- 数据源：同源 fixture（角色/武器/魔之楔 3 类型，8 个委托），固定时钟 `2026-08-12T10:30:00+08:00`，刷新倒计时 1800s（动态字段已 mask）。
- 对比资料（不入 Git）：`/var/folders/kz/__ln6hkx1tx_9zy0ytx3_k200000gn/T/dnaby-render-compare-8r6ik1xv`

## 画布尺寸

- legacy `draw_mh_simple`：1040 × 646
- rewrite `render_mh`：1300 × 504
- 结论：**结构性差异**（legacy 为横向卡片，rewrite 为 1300 宽纵向布局）。

## rewrite 文本元数据（供人工核对 legacy 画面内容）

```
二重螺旋 · 密函
角色:
扼守/无尽 (id=601)
拆解 (id=602)
追缉 (id=604)
武器:
扼守/无尽 (id=621)
勘探/无尽 (id=623)
魔之楔:
扼守/无尽 (id=641)
追缉 (id=644)
调停 (id=646)
```

## rewrite 布局段

```
[
  {
    "name": "角色",
    "start": 100,
    "height": 164,
    "items": 3
  },
  {
    "name": "武器",
    "start": 264,
    "height": 130,
    "items": 2
  },
  {
    "name": "魔之楔",
    "start": 394,
    "height": 164,
    "items": 3
  }
]
```

## rewrite 资源语义

```
[
  {
    "kind": "font",
    "key": "dna_fonts",
    "status": "fallback",
    "source": ""
  }
]
```

## 像素弱信号

- RGB 直方图余弦距离：0.9870（0=相同）
- 像素统计：{"相同像素率": 0.0, "差异区域": "x[0..1299] y[0..503]", "说明": "legacy 已 resize 到 rewrite 画布后的近似信号，不作通过依据"}

## 结论

- 结构性对比：两图绘制内容同源（角色/武器/魔之楔 + 委托名逐一对应），但画布尺寸与 布局方式不同（legacy 横向卡片 vs rewrite 纵向 1300 宽），**结构性差异**。
- rewrite 侧文本/布局/资源语义可由元数据自动核对；legacy 侧文本画入图内，需人工 查看 `legacy_mh_simple.png` 核对角色名/委托名/轮换时间文案。
- 像素相似度低属于布局差异的必然结果，不设通过阈值；视觉等价由人工确认。
