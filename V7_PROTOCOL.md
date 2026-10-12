# V7：第3候補の文脈とpair判断の不変性

状態：探索的な別campaign．V6の科学的出力を読む前に設計する．V6のconfirmatory familyへ加えない．
対象：V6独立oracle合格96itemsから，各8familyのparameter_index 0,3,6,9を固定選択した32items．judge outcomeを選択に使わない．
構成：3つのV6構成×32items×2criteria×2arms×2orders×2contexts＝1,536calls．cloneは含めない．全callを直列，V6終了後のみ実行する．
arms：equivalenceはgoodとequivalentのpair，第三候補Cはverified-bad．signalはgoodとverified-badのpair，Cはequivalent．
contexts：absentではCを示さず，presentではA/Bの後ろへCを示す．Cは選択対象ではない．A/B pair内容，specification，system rubric，出力schemaはcontexts間で同一．AB/BAはpair内のみ交換．これはCの全位置permutationを検証する実験ではない．
rubric：V6と同じfunctional correctness on declared inputsとneutral/strict．両contextsに共通の「A/Bだけを比較し，参考Cを選択対象に含めない」というinstructionを加える．V6とV7のbaselineは同一promptではないため直接差分を因果効果と呼ばない．
schedule：seed2026100807で512slotsを事前shuffleし，各configへ同一scheduleを適用．configsはV6のexact copy．
primary descriptive endpoint：32tasks中，どちらかのorderでcontext間のcanonical winnerが異なる，または4callsのいずれかinvalidとなるtaskの割合．全12config/criterion/armセルを報告する．invalid同士を不変として数えない．
utility：各contextのtask内AB/BA成功平均．signalはgood選択，equivalenceはtieを成功とする．invalid/tie-on-signal/wrongは0．paired context-present minus absentを8family×4tasksのstratified bootstrap 20,000回，type7の2.5/97.5 percentileで記述．seed full SHA256(manifestSHA+':'+configID+':'+criterion+':'+arm+':v7-context')．探索的CIであり多重検定を経たconfirmatory claimではない．
admission：512slots/configが揃いserved model一致，invalid<=1%の時のみfullanalysis．partial/HOLDは観測coverageと無効数のみ，欠損taskを勝手に除外した完全結果を作らない．
時間：実行開始から90分または2026-10-09 05:35 JSTの早い方まで新規dispatch．transport/model mismatchで停止，retryなし．実行前intentとterminalをfsync．最終dangling intentはambiguousでHOLD，再送しない．
ChiralityEvalとの関係：第三候補の文脈によるpairの不変性を測る．embedding geometry，wedge/NDI，PVR-alt，3候補全順序rank，HodgeRankの実証を代替しない．正解tieを含むためparity undefinedを成功へ変換しない．
time-box：新しいモデルやembeddingを探索せず，上記1,536callsと解析・再現artifactで切る．weak signalはcontext変更によるpaired変化．killはoracle/source drift，transport障害，V6未完了，90分超過．結果が変化ゼロでも全セルを残す．
