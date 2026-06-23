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

### H-3: 20万円サテライトポートフォリオは機会損失を減らせるか（正式運用へ昇格）

**状態**: B枠仮説ではなく、正式なデフォルトポートフォリオとして運用する。現行100万円ポートフォリオは `data/portfolio_100man.csv` に残し、20万円ポートフォリオは `data/portfolio_20man.csv` をデフォルトにする。

**背景**: 100万円枠は最大5銘柄・1銘柄25%上限の分散モメンタム運用。別軸として、20万円規模で小口・高稼働のポートフォリオを並走させ、100万円枠ではサイズや集中の都合で取り逃がす機会を検証する。

**運用ルール**:
- 総予算: 200,000円（A枠の為替前提 ¥1,000,000 ≒ $6,700 から概算 $1,340）
- 同一銘柄の同時保有は最大2株
- 基本はキャッシュ稼働率85%以上を目指す
- ただし、A枠と同じ品質ゲートを満たさない銘柄では現金を残す
- `catalyst_quality == WEAK`、score < 7.0、stop未設定、CRITICAL data gap はBUY禁止
- 高単価銘柄で1株が予算の50%を超える場合は、全ゲート通過かつリスクリワード2.0以上のときだけ1株許可

**追加したほうがよい判定ルール**:
- 現金を残す理由を必ず記録する（基準未達なのか、価格が高すぎるのか、イベント前回避なのか）
- A枠と同じtickerを持つ場合は、相関リスクとしてnoteに明記する
- 決算・FOMC・CPIなど48時間以内のギャップイベント前は、新規BUYを原則WAITにする
- 1株しか買えない銘柄より、同等の期待値で2銘柄に分散できる候補を優先する
- 4週間以上含み損かつテーゼ未進展なら、資金効率低下としてexit review対象にする

**運用方法**:
- `/decision` はデフォルトで20万円ポートフォリオを対象にする
- 100万円側を扱う場合は `python skills/portfolio.py list --portfolio 100man` のように明示する
- 比較時は20万円枠単体のキャッシュ稼働率、勝率、平均リターン、最大ドローダウンを確認する

**判定基準**:
- H-3平均リターン ≥ A枠平均リターン × 0.8、かつ勝率50%以上 → 仮説支持
- H-3最大ドローダウンがA枠より大きく、平均リターンもA枠未満 → 仮説棄却
- キャッシュ稼働率85%以上の週が半数未満 → 20万円制約が運用に不向き、ルール再設計

**検証期間**: 2026-06-20 〜 2026-09-20（3ヶ月、H-3クローズドトレード5件以上を目標）

**B枠エントリー条件**（毎回明記）:
```
[H-3] 20万円枠。稼働率=XX%、同一銘柄保有=Y/2株、現金残=XX%。採用/現金残し理由: ...
```

---

### H-4: 100万円シミュレーション枠は高稼働にした方が decision 精度改善に効くか

**状態**: 運用中。`data/portfolio_100man.csv` は実弾ではなく、decision の精度改善に使うシミュレーション枠として扱う。

**背景**: 100万円枠はお金を動かす場所ではなく、「どの判断・サイズ・見送りが実際にどうなったか」を集めるための場所。したがって、20万円実運用枠よりもキャッシュ温存の価値は低く、品質ゲートを通過した候補があるなら予算をより使い切る方が検証データが増える。

**運用ルール**:
- 総予算: 1,000,000円（概算 $6,700）
- 最大5銘柄、1銘柄上限25%（概算 $1,675）
- 採用品質ゲートは20万円枠と同じ。`catalyst_quality == WEAK`、score < 7.0、stop未設定、CRITICAL data gap はBUY禁止
- 有資格候補がある場合、キャッシュ稼働率90〜100%を目指す
- HIGHは原則25%上限まで使う。MEDIUMは15〜20%を許容する
- LOWは観察用サイズまで。LOWで現金を埋めることは禁止
- 稼働率90%未満で終える場合は、候補不足・イベント前・セクター集中・データ不足のどれが理由かを記録する

**記録形式**:
```
[100man-sim] 稼働率=XX%。品質ゲート通過。サイズ根拠: HIGH 25% / MEDIUM 15-20% / 現金残し理由: ...
```

**判定基準**:
- 高稼働シミュレーションの8週間後alphaが20万円枠より高い、またはdecisionのBUY/PASS校正に有意な反例を増やす → 仮説支持
- 高稼働化でLOW品質・過熱エントリーが増え、勝率/alphaが悪化 → 仮説棄却

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
