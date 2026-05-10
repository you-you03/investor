# 仮説トラッカー

「このやり方が最適か」を検証するための仮説管理ドキュメント。
仮説を1〜2個に絞り、期間・判定基準・測定方法を事前に定義してから検証する。

---

## アクティブ仮説

### H-1: Watchlist ESCALATE銘柄はmarket-scan銘柄より勝率が高い

**背景**: ウォッチリストで深研究した後にESCALATEされた銘柄は、当日のmarket-scanで発掘された銘柄より事前情報が豊富。その分、確信度精度が高いはずという直感がある。

**検証方法**:
- `data/portfolio.csv` の `signal_type` フィールドで分類
- `watchlist_escalate` vs `earnings_beat / technical_breakout / analyst_upgrade` を比較
- 測定指標: 平均リターン、勝率（クローズドトレードのみ）

**判定基準**:
- ESCALATE勝率 ≥ market-scan勝率 + 10pp → 仮説支持
- ESCALATE平均リターン ≥ market-scan平均リターン × 1.2 → 仮説支持
- どちらも満たさない → 仮説棄却、ウォッチリスト深研究の優先度を下げる

**検証期間**: 2026-05-10 〜 2026-08-10（3ヶ月、クローズドトレード10件以上を目標）

**現在のデータ**（2026-05-10時点）:

| signal_type | 件数 | 勝率 | 平均リターン |
|---|---|---|---|
| watchlist_escalate | 2 (TSM, UAL) | 未クローズ | — |
| earnings_beat | 4 | 75% | +14.9%* |
| technical_breakout | 3 | 100% | +21.9% |
| analyst_upgrade | 3 | 100% | +38.3% |

*NVDAの-4.72%を含む。データ少なく判断保留。

**コマンド**（判定実行時）:
```bash
# signal_type別成績を集計
python -c "
import csv
from collections import defaultdict
rows = list(csv.DictReader(open('data/portfolio.csv')))
closed = [r for r in rows if r['status']=='closed' and r['exit_price']]
by_type = defaultdict(list)
for r in closed:
    ret = (float(r['exit_price'])-float(r['entry_price']))/float(r['entry_price'])*100
    by_type[r['signal_type']].append(ret)
for t, rets in sorted(by_type.items()):
    wins = sum(1 for r in rets if r>0)
    print(f'{t}: {len(rets)}件 勝率{wins/len(rets):.0%} 平均{sum(rets)/len(rets):+.1f}%')
"
```

---

### H-2: RSI>80でもSECTOR_LEADING条件なら縮小エントリーは正当化される

**背景**: MRVL(RSI=79.75)をWAITして+28%を逃した。強モメンタム相場では押し目が来ない可能性がある。
現ルール（修正済み）:
- RSI ≥ 85 → WAIT無条件（NVDA RSI=92.8の遡及分析で特例適用が誤作動することを確認）
- RSI 70–84 かつ 52W高値3%以内 → WAIT無条件
- RSI 70–84 かつ 52W高値3%外 かつ SECTOR_LEADING → 縮小エントリー可（特例）
仮説: 上記「縮小エントリー可」ケース（RSI 70–84×SECTOR_LEADING×非52W高値圏）は、WAITより期待値が高い。

**検証方法**:
- B枠（`data/paper_portfolio.csv`）でRSI>70かつSECTOR_LEADING銘柄を仮想エントリー（縮小サイズ）
- A枠（`data/portfolio.csv`）ではWAITを継続
- 両者のリターンを8週後に比較

**判定基準**:
- B枠（縮小エントリー）リターン > 0% → 仮説支持（WAITのゼロリターンに勝る）
- B枠平均リターン > A枠同期間の全トレード平均 × 0.7 → サイズ縮小コストを補えている → 仮説強支持
- B枠勝率 < 50% → 仮説棄却、RSI WAITルールを維持

**検証期間**: 2026-05-10 〜 2026-07-10（2ヶ月）

**B枠エントリー条件**（毎回明記）:
```
[H-2検証] RSI=XX, SECTOR=LEADING, 52W高値距離=XX% → B枠縮小エントリー
```

**コマンド**（判定実行時）:
```bash
python skills/paper_portfolio.py compare
```

---

## 完了済み仮説

（判定が出たものをここに移動する）

---

## B枠 運用ルール

B枠（paper portfolio）は実弾を使わずに仮説を検証するための仮想ポートフォリオ。

- **B枠エントリー**: `python skills/decision.py --paper --send '[...]'`
- **B枠一覧**: `python skills/paper_portfolio.py list`
- **B枠クローズ**: `python skills/paper_portfolio.py close --ticker X --price Y`
- **A/B比較**: `python skills/paper_portfolio.py compare`

B枠トレードの`note`フィールドには必ず仮説ID（例: `[H-2]`）を記載する。
