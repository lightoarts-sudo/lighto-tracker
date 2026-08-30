(() => {
  "use strict";

  // 退休試算：以使用者自訂的假設做逐月模擬，並把「借錢投入」的成本與風險
  // 一併算進去。所有數字都由輸入推導，頁面本身不提供任何標的或做法建議。
  const TAB_LABEL = "退休計算機";
  const TAB_FLAG = "data-retire-tab";
  const PANEL_FLAG = "data-retire-panel";
  const STORE_KEY = "popostock-retirement-v1";

  let active = false;
  let state = null;

  // 近十年價格年化報酬，取自本站行情（2016-08 → 2026-08，未含股息／配息）。
  // 這是「過去發生過什麼」，不是未來預期；半導體那一欄尤其是極端值。
  const REF_HINT =
    "近十年年化（本站行情試算，未含股息）：台股 +17.6%｜S&P 500 +13.5%｜" +
    "納斯達克100 +19.9%｜美股半導體SMH +32.5%。以上為過去表現，" +
    "長期規劃一般採較保守的 6–8%。";

  // 曝險＝部位跟隨市場的倍數（正二＝2），由持股結構決定；
  // 貸款則是擴大投入本金。兩者獨立，模型也分開處理。
  const EXPOSURE_HINT =
    "100% 不開槓桿；持有正二（2 倍槓桿 ETF）即為 200%。" +
    "此欄只決定部位跟隨市場的倍數，與貸款無關——貸款是把借來的錢加進本金。";

  const DEFAULTS = {
    age: 35,
    retireAgeCap: 90,
    portfolio: 1000000,
    cashReserve: 500000,
    monthlyExpense: 40000,
    monthlySurplus: 30000,
    monthlyInvest: 30000,
    annualReturn: 7,
    withdrawRate: 4,
    withdrawStartAge: 60,
    investUntilAge: 60,
    targetExposure: 200,
    loans: [{ amount: 1000000, rate: 4, months: 120, startAge: 35 }],
  };

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const saved = { ...DEFAULTS, ...JSON.parse(raw) };
        // 舊版存檔沒有 startAge，一律視為「現在就貸」，結果與升級前一致。
        saved.loans = (saved.loans || []).map((l) => ({
          ...l,
          startAge: l.startAge === undefined ? Number(saved.age || 0) : l.startAge,
        }));
        return saved;
      }
    } catch (error) {
      // 私密視窗或封鎖儲存時直接用預設值，不能讓頁面因此打不開。
    }
    return { ...DEFAULTS, loans: DEFAULTS.loans.map((l) => ({ ...l })) };
  }

  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch (error) {
      /* 存不進去不影響試算 */
    }
  }

  function style() {
    if (document.getElementById("retire-style")) return;
    const el = document.createElement("style");
    el.id = "retire-style";
    el.textContent = [
      ".retire-panel{background:#fff;border:1px solid #c8d6e8;border-radius:8px;",
      "box-shadow:0 14px 34px rgba(3,24,63,.1);padding:20px 20px 24px}",
      ".retire-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 18px;margin:0 0 4px}",
      ".retire-head h2{font-size:20px;font-weight:800;color:#12295c;margin:0}",
      ".retire-head .meta{color:#667483;font-size:13px;font-weight:700}",
      ".retire-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));",
      "gap:12px;margin:14px 0}",
      ".retire-field label{display:block;font-size:12.5px;font-weight:800;color:#5b6b80;margin-bottom:4px}",
      ".retire-field input{width:100%;border:1px solid #c8d6e8;border-radius:8px;padding:8px 10px;",
      "font-size:15px;font-weight:800;color:#12295c;font-variant-numeric:tabular-nums}",
      ".retire-field .hint{font-size:11.5px;color:#8b98ab;font-weight:700;margin-top:3px;line-height:1.6}",
      ".retire-sub{font-size:15px;font-weight:900;color:#12295c;margin:16px 0 8px;",
      "display:flex;align-items:center;gap:10px}",
      ".retire-sub button{border:1px solid #c8d6e8;background:#fff;color:#5b6b80;font-size:12.5px;",
      "font-weight:800;border-radius:999px;padding:4px 12px;cursor:pointer}",
      ".retire-sub button:hover{background:#f4f7fb}",
      ".retire-loan{display:grid;grid-template-columns:repeat(4,1fr) auto;gap:8px;",
      "align-items:end;margin-bottom:8px}",
      ".retire-loan .del{border:1px solid #f0c8c8;background:#fff;color:#d64038;font-size:12.5px;",
      "font-weight:800;border-radius:8px;padding:8px 12px;cursor:pointer;height:37px}",
      ".retire-sum{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 6px}",
      ".retire-stat{background:#f4f7fb;border:1px solid #e2e8f2;border-radius:12px;",
      "padding:10px 16px;min-width:150px;flex:1}",
      ".retire-stat b{display:block;font-size:21px;color:#12295c;font-weight:900;line-height:1.3}",
      ".retire-stat span{font-size:12.5px;color:#667483;font-weight:700}",
      ".retire-stat.warn{background:#fff5f5;border-color:#f0c8c8}",
      ".retire-stat.warn b{color:#d64038}",
      ".retire-stat.good b{color:#2f8d4e}",
      ".retire-note{margin-top:14px;color:#667483;font-size:12.5px;line-height:1.75}",
      ".retire-note b{color:#d64038}",
      ".retire-scroll{overflow-x:auto;margin-top:6px}",
      ".retire-table{width:100%;border-collapse:collapse;font-size:14px;min-width:640px}",
      ".retire-table th{text-align:right;padding:9px 12px;color:#cfdcf0;font-weight:800;",
      "font-size:12.5px;white-space:nowrap;border-bottom:2px solid #e2e8f2}",
      ".retire-table th:first-child{text-align:left}",
      ".retire-table td{text-align:right;padding:9px 12px;border-bottom:1px solid #eef2f7;",
      "color:#12295c;font-variant-numeric:tabular-nums;white-space:nowrap}",
      ".retire-table td:first-child{text-align:left;font-weight:800}",
      ".retire-table tbody tr:hover{background:#f8fafd}",
      ".retire-table tr.milestone td{background:#fffbe9}",
      ".retire-table tr.milestone td:first-child::after{content:\" ★\";color:#e8bd22}",
      ".retire-flag{display:inline-block;font-size:11px;font-weight:900;border-radius:999px;",
      "padding:1px 8px;margin-left:6px;background:#12295c;color:#fff}",
      "[" + PANEL_FLAG + "] .retire-flag.set{background:#e8bd22;color:#12295c}",
    ].join("");
    document.head.appendChild(el);
  }

  const shell = () => document.querySelector(".tracker-shell");
  const strip = () => document.querySelector(".workspace-tabs");
  const ourTab = () => document.querySelector("[" + TAB_FLAG + "]");
  const ourPanel = () => document.querySelector("[" + PANEL_FLAG + "]");

  function reactPanels() {
    const host = shell();
    const bar = strip();
    if (!host || !bar) return [];
    const children = Array.from(host.children);
    return children.slice(children.indexOf(bar) + 1).filter((n) => !n.hasAttribute(PANEL_FLAG));
  }

  const money = (v) =>
    v === null || !isFinite(v) ? "—" : Math.round(v).toLocaleString("zh-TW");
  // 需要看到零頭時用的兩位小數版本（每年支出這種金額不大、差幾千元也有意義）。
  const wan2 = (v) =>
    !isFinite(v) ? "—" : (v / 10000).toLocaleString("zh-TW", {
      minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " 萬";

  const wan = (v) => (!isFinite(v) ? "—" : (v / 10000).toLocaleString("zh-TW", {
    minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " 萬");

  // 等額本息月付金；利率為 0 時退化成本金均攤。
  function monthlyPayment(amount, annualRatePct, months) {
    if (!amount || !months) return 0;
    const r = annualRatePct / 100 / 12;
    if (r <= 0) return amount / months;
    return (amount * r) / (1 - Math.pow(1 + r, -months));
  }

  function simulate(s) {
    const startAge = Number(s.age || 0);
    // 起貸月：第 1 個月代表「現在就貸」。過去的年齡一律夾到現在，不回溯。
    const loanMonth = (l) =>
      Math.max(1, Math.round((Number(l.startAge ?? startAge) - startAge) * 12) + 1);
    const loans = (s.loans || [])
      .filter((l) => l.amount > 0 && l.months > 0)
      .map((l) => ({ ...l, startMonth: loanMonth(l) }));
    const borrowed = loans.reduce((sum, l) => sum + Number(l.amount || 0), 0);
    // 只有「現在就貸」的錢算進起始本金；未來才貸的在該月才撥入。
    const drawnNow = loans.filter((l) => l.startMonth === 1);
    const borrowedNow = drawnNow.reduce((sum, l) => sum + Number(l.amount || 0), 0);
    const payment = drawnNow.reduce(
      (sum, l) => sum + monthlyPayment(Number(l.amount), Number(l.rate), Number(l.months)),
      0,
    );
    const maxMonths = loans.reduce((m, l) => Math.max(m, Number(l.months)), 0);

    // 借來的錢一次投入，所以起始部位包含貸款本金。
    const startAssets = Number(s.portfolio || 0) + borrowedNow;
    const ownCapital = Number(s.portfolio || 0);
    // 曝險倍數來自持有槓桿型 ETF（正二＝2 倍），與借貸無關：
    // 借來的錢只是讓「投入本金」變大，曝險則決定這筆本金放大幾倍跟隨市場。
    const leverage = Math.max(0, Number(s.targetExposure || 100)) / 100;
    const marketExposure = startAssets * leverage;
    // 相對自有資金的總曝險：貸款與槓桿兩者的效果相乘。
    const exposure = ownCapital > 0 ? (marketExposure / ownCapital) * 100 : null;

    const monthlyIncome = Number(s.monthlyExpense || 0) + Number(s.monthlySurplus || 0);
    const annualIncome = monthlyIncome * 12;
    const annualExpense = Number(s.monthlyExpense || 0) * 12;
    const target = annualExpense / (Number(s.withdrawRate || 4) / 100);

    const indexReturn = Number(s.annualReturn || 0) / 100;
    // 2 倍槓桿部位的價值變動約為指數的兩倍（此處未計入每日重設的耗損與內含費用，
    // 實際長期報酬會低於這個數字，頁面下方有說明）。
    const r = indexReturn * leverage;
    const monthlyRate = Math.pow(1 + r, 1 / 12) - 1;

    let assets = startAssets;
    // 各筆貸款分開攤還，才能正確反映不同期數結束的時點。
    const balances = loans.map((l) => ({
      balance: Number(l.amount),
      rate: Number(l.rate) / 100 / 12,
      months: Number(l.months),
      pay: monthlyPayment(Number(l.amount), Number(l.rate), Number(l.months)),
      left: Number(l.months),
      startMonth: l.startMonth,
      // 未撥款前既不算負債，也不算進資產。
      drawn: l.startMonth === 1,
    }));

    const rows = [];
    let incomeCrossAge = null;
    let retireAge = null;
    let peakPayment = payment;
    const totalMonths = Math.max(1, (Number(s.retireAgeCap || 90) - startAge) * 12);

    let firstMonthInvest = null;
    let withdrawn = 0;
    let invested = 0;
    // 現金水位：每月盈餘扣掉要投入股市的部分，剩下的存起來。
    // 貸款月付金不在這裡扣——它已經從「可投入金額」裡扣過，重複扣會少算現金。
    const monthlyCash = Math.max(0, Number(s.monthlySurplus || 0) - Number(s.monthlyInvest || 0));
    let cash = Number(s.cashReserve || 0);
    for (let m = 1; m <= totalMonths; m += 1) {
      // 到期起貸的那一筆，本金在當月撥入股市，同月開始還款。
      balances.forEach((b) => {
        if (!b.drawn && b.startMonth === m) {
          b.drawn = true;
          assets += b.balance;
        }
      });
      // 當月仍在攤還的貸款月付金：還沒撥款或已繳完的都不扣，投入金額會自動回升。
      const duePayment = balances.reduce((sum, b) => sum + (b.drawn && b.left > 0 ? b.pay : 0), 0);
      if (duePayment > peakPayment) peakPayment = duePayment;
      const ageNow = startAge + m / 12;
      // 過了「可投入到幾歲」就不再有工作收入可投入。
      const canInvest = ageNow <= Number(s.investUntilAge || 999);
      const invest = canInvest ? Math.max(0, Number(s.monthlyInvest || 0) - duePayment) : 0;
      if (firstMonthInvest === null) firstMonthInvest = invest;
      assets = assets * (1 + monthlyRate) + invest;
      invested += invest;
      // 沒有工作收入之後就不再有新的盈餘可存。
      if (canInvest) cash += monthlyCash;
      // 到達提領年齡後，每月依提領率的十二分之一自資產提出並累計。
      if (ageNow >= Number(s.withdrawStartAge || 999)) {
        const take = Math.max(0, (assets - 0) * (Number(s.withdrawRate || 4) / 100) / 12);
        assets = Math.max(0, assets - take);
        withdrawn += take;
      }
      let debt = 0;
      balances.forEach((b) => {
        if (b.drawn && b.left > 0) {
          const interest = b.balance * b.rate;
          b.balance = Math.max(0, b.balance + interest - b.pay);
          b.left -= 1;
        }
        debt += b.drawn ? b.balance : 0;
      });
      const net = assets - debt;
      const age = startAge + m / 12;

      if (incomeCrossAge === null && net * r >= annualIncome && annualIncome > 0) {
        incomeCrossAge = age;
      }
      if (retireAge === null && net >= target && target > 0) retireAge = age;

      if (m % 12 === 0) {
        rows.push({
          age: startAge + m / 12,
          assets,
          debt,
          net,
          passive: net * r,
          withdraw: net * (Number(s.withdrawRate || 4) / 100),
          withdrawn,
          invested,
          cash,
          totalWealth: net + cash,
        });
      }
    }

    const loanRate = loans.length
      ? loans.reduce((sum, l) => sum + Number(l.rate) * Number(l.amount), 0) / (borrowed || 1)
      : 0;

    return {
      loans, borrowed, borrowedNow, payment, peakPayment, maxMonths, startAssets, ownCapital, exposure,
      monthlyIncome, annualIncome, annualExpense, target, rows,
      leverage, marketExposure, indexReturn, effectiveReturn: r,
      totalWithdrawn: withdrawn,
      totalInvested: invested,
      monthlyCash, finalCash: cash,
      actualInvest: firstMonthInvest,
      investShortfall: payment > Number(s.monthlyInvest || 0),
      incomeCrossAge, retireAge, loanRate,
      paymentOverSurplus: peakPayment > Number(s.monthlySurplus || 0),
      returnBelowLoan: loans.length > 0 && r * 100 <= loanRate,
    };
  }

  // 上下鍵的級距：金額欄位用整數級距才好調，比率欄位用小數。
  // 先前改成 type=text 是為了讓打字順暢，但真正的原因是「每按一鍵重繪整個面板」，
  // 那個已改為只重繪結果區，所以改回 number 可以同時保有打字與上下鍵。
  const STEP = {
    age: 1, retireAgeCap: 1,
    portfolio: 10000,
    cashReserve: 10000,
    monthlyExpense: 1000, monthlySurplus: 1000, monthlyInvest: 1000,
    annualReturn: 0.5, withdrawRate: 0.1, targetExposure: 10,
    withdrawStartAge: 1, investUntilAge: 1,
  };

  // 金額欄位顯示千分位。HTML type=number 不接受逗號，所以這些改用 text，
  // 上下鍵改由下方的 keydown 自行處理，功能與 number 相同。
  const MONEY_KEYS = new Set([
    "portfolio", "cashReserve", "monthlyExpense", "monthlySurplus", "monthlyInvest",
  ]);
  const group = (v) =>
    v === "" || v === null || v === undefined || !isFinite(Number(v))
      ? ""
      : Number(v).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
  const ungroup = (v) => String(v).replace(/,/g, "").trim();

  function field(key, label, hint) {
    if (MONEY_KEYS.has(key)) {
      return (
        '<div class="retire-field"><label>' + label + "</label>" +
        '<input type="text" inputmode="numeric" autocomplete="off" data-money="1" step="' +
        (STEP[key] ?? 1) + '" data-key="' + key + '" value="' + group(state[key]) + '">' +
        (hint ? '<div class="hint">' + hint + "</div>" : "") + "</div>"
      );
    }
    return (
      '<div class="retire-field"><label>' + label + "</label>" +
      '<input type="number" inputmode="decimal" autocomplete="off" step="' +
      (STEP[key] ?? 1) + '" data-key="' + key + '" value="' + (state[key] ?? "") + '">' +
      (hint ? '<div class="hint">' + hint + "</div>" : "") + "</div>"
    );
  }


  // 結果區獨立產生：打字時只換這一塊，輸入框不會被銷毀重建，游標也不會跳。
  function resultsHtml(s) {
    // 兩種標籤：達成型（由試算算出）與設定型（使用者自己指定的年齡）。
    // 設定型只在該年齡確實落在表格範圍內時才標，否則會標在不存在的列上。
    const stopWorkAge = Math.ceil(Number(state.investUntilAge || 0));
    const drawAge = Math.ceil(Number(state.withdrawStartAge || 0));
    const inRange = (age) =>
      age > Number(state.age || 0) && age <= Number(state.retireAgeCap || 0);

    // 每筆貸款的起貸年齡（同一年可能有多筆，去重後只標一次）。
    const loanAges = new Set(
      (s.loans || [])
        .filter((l) => l.startMonth > 1)
        .map((l) => Math.ceil(Number(l.startAge))),
    );

    const milestones = new Set();
    if (s.incomeCrossAge) milestones.add(Math.ceil(s.incomeCrossAge));
    if (s.retireAge) milestones.add(Math.ceil(s.retireAge));
    loanAges.forEach((age) => { if (inRange(age)) milestones.add(age); });
    if (inRange(stopWorkAge)) milestones.add(stopWorkAge);
    if (inRange(drawAge)) milestones.add(drawAge);

    const body = s.rows
      .filter((row) => row.age % 1 === 0)
      .map((row) => {
        const tags = [];
        if (loanAges.has(row.age) && inRange(row.age)) {
          tags.push('<span class="retire-flag set">開始貸款</span>');
        }
        if (inRange(stopWorkAge) && stopWorkAge === row.age) {
          tags.push('<span class="retire-flag set">開始無工作收入</span>');
        }
        if (inRange(drawAge) && drawAge === row.age) {
          tags.push('<span class="retire-flag set">開始提領</span>');
        }
        if (s.retireAge && Math.ceil(s.retireAge) === row.age) tags.push('<span class="retire-flag">達 4% 退休門檻</span>');
        if (s.incomeCrossAge && Math.ceil(s.incomeCrossAge) === row.age) tags.push('<span class="retire-flag">報酬超越工作收入</span>');
        return (
          '<tr' + (milestones.has(row.age) ? ' class="milestone"' : "") + ">" +
          "<td>" + row.age + " 歲" + tags.join("") + "</td>" +
          "<td>" + wan(row.assets) + "</td>" +
          "<td>" + wan(row.debt) + "</td>" +
          "<td>" + wan(row.net) + "</td>" +
          "<td>" + wan(row.passive) + "</td>" +
          "<td>" + wan(row.cash) + "</td>" +
          "<td>" + wan(row.totalWealth) + "</td>" +
          "<td>" + (row.withdrawn > 0 ? wan(row.withdrawn) : "—") + "</td></tr>"
        );
      })
      .join("");
    return (
      '<div class="retire-sum">' +
      '<div class="retire-stat"><b>' + money(s.monthlyIncome) + "</b><span>推估月收入（支出＋盈餘）</span></div>" +
      '<div class="retire-stat"><b>' + money(s.payment) + "</b><span>貸款月付金合計（目前）" +
      (s.peakPayment > s.payment ? "；期間最高 " + money(s.peakPayment) : "") + "</span></div>" +
      '<div class="retire-stat' + (s.investShortfall ? " warn" : "") + '"><b>' +
      money(s.actualInvest) + "</b><span>每月實際投入（可投入−月付金）</span></div>" +
      '<div class="retire-stat' + (s.exposure && s.exposure > 150 ? " warn" : "") + '"><b>' +
      (s.exposure ? s.exposure.toFixed(0) + "%" : "—") + "</b><span>目前曝險（總部位÷自有）</span></div>" +
      '<div class="retire-stat"><b>' + money(s.marketExposure) + "</b><span>名目市場曝險（參考，非帳戶價值）</span></div>" +
      '<div class="retire-stat"><b>' + (s.effectiveReturn * 100).toFixed(1) + "%</b><span>有效年化＝指數 " + (s.indexReturn * 100).toFixed(1) +
      "% × " + s.leverage.toFixed(2) + " 倍</span></div>" +
      '<div class="retire-stat"><b>' + wan(s.target) + "</b><span>退休所需資產（" +
      state.withdrawRate + "% 提領）</span></div>" +
      '<div class="retire-stat' + (s.incomeCrossAge ? " good" : "") + '"><b>' +
      (s.incomeCrossAge ? Math.ceil(s.incomeCrossAge) + " 歲" : "未達成") +
      "</b><span>投資報酬超越工作收入</span></div>" +
      '<div class="retire-stat"><b>' + wan2(s.annualExpense) + "</b><span>每年支出金額</span></div>" +
      '<div class="retire-stat"><b>' + money(s.monthlyCash) + "</b><span>每月存下現金（盈餘−可投入）</span></div>" +
      '<div class="retire-stat"><b>' + wan(s.finalCash) + "</b><span>現金水位（至 " +
      state.retireAgeCap + " 歲）</span></div>" +
      '<div class="retire-stat"><b>' + wan(s.totalInvested) + "</b><span>持續投入金額（至 " +
      state.investUntilAge + " 歲）</span></div>" +
      '<div class="retire-stat"><b>' + wan(s.totalWithdrawn) + "</b><span>累計提領（至 " +
      state.retireAgeCap + " 歲）</span></div>" +
      '<div class="retire-stat' + (s.retireAge ? " good" : "") + '"><b>' +
      (s.retireAge ? Math.ceil(s.retireAge) + " 歲" : "未達成") +
      "</b><span>達 " + state.withdrawRate + "% 提領門檻</span></div>" +
      "</div>" +
      (s.paymentOverSurplus
        ? '<p class="retire-note"><b>注意：</b>期間最高貸款月付金 ' + money(s.peakPayment) +
          " 元已超過每月盈餘 " + money(state.monthlySurplus) +
          " 元，代表要動用其他資金才付得出來，這個情境在現實中難以維持。</p>"
        : "") +
      (s.returnBelowLoan
        ? '<p class="retire-note"><b>注意：</b>預期年化報酬 ' + state.annualReturn +
          "% 未高於加權貸款利率 " + s.loanRate.toFixed(2) +
          "%，借錢投入在這個假設下是負貢獻。</p>"
        : "") +
      '<div class="retire-scroll"><table class="retire-table"><thead><tr>' +
      "<th>年齡</th><th>總資產</th><th>貸款餘額</th><th>淨資產</th>" +
      "<th>年報酬金額</th><th>現金</th><th>總淨值</th><th>累計提領</th>" +
      "</tr></thead><tbody>" + body + "</tbody></table></div>" +
      '<p class="retire-note">' +
      "試算方式：投入本金＝現有股票＋現在動用的貸款（借來的錢一次投入）；設定為未來年齡的貸款，於該年撥入股市並同時開始還款，撥款前不計入資產與負債；市場曝險＝本金×曝險倍數，" +
      "有效年化＝預期年化×曝險倍數（倍數只在此處使用一次，本金不重複放大）；" +
      "每月以有效年化換算的月報酬複利成長，" +
      "每月投入以「可投入金額−當月貸款月付金」計算，貸款繳清後投入金額自動回升；" +
      "現金水位＝現金儲備＋每月（盈餘−可投入金額）累加，貸款月付金不重複自現金扣除；" +
      "現金不計入報酬成長，也不計入 4% 提領門檻的判定（該門檻只看股票淨資產）；" +
      "再加上每月可投入金額；各筆貸款分別以等額本息攤還，淨資產＝總資產−貸款餘額。" +
      "「投資報酬超越工作收入」以淨資產×年化報酬 ≧ 年收入判定；「退休門檻」以淨資產 ≧ 年支出÷提領率判定。<br>" +
      "<b>這是一份試算，不是預測，更不是建議。</b>實際報酬每年都會波動甚至為負，模型假設每年固定報酬，" +
      "會低估過程中的下跌風險。<b>曝險倍數是雙向的</b>：200% 曝險在市場下跌時虧損也是兩倍，" +
      "且槓桿型 ETF 每日重設，盤整或波動劇烈時會產生耗損，長期報酬通常低於指數的兩倍，" +
      "本試算未計入該耗損與內含費用，因此高曝險情境會偏樂觀。" +
      "借錢投資同樣會放大獲利與虧損，且不論市場漲跌都必須按月還款。" +
      "4% 提領率源自美國歷史研究，未必適用於不同市場、稅制與壽命假設。" +
      "請自行評估或諮詢合格理財顧問。</p>"
    );
  }

  function orderHtml(s) {
    return (
      "現有股票 " + money(state.portfolio) + " ＋ 現在動用的貸款 " + money(s.borrowedNow) +
      " ＝ 本金 " + money(s.startAssets) + "。<br>" +
      (s.borrowed > s.borrowedNow
        ? "另有 " + money(s.borrowed - s.borrowedNow) + " 於設定的年齡才撥入，不計在起始本金。<br>"
        : "") +
      "曝險 " + s.leverage.toFixed(2) + " 倍只作用在報酬率：有效年化 " +
      (s.effectiveReturn * 100).toFixed(1) + "% ＝ 指數 " + (s.indexReturn * 100).toFixed(1) +
      "% × " + s.leverage.toFixed(2) + " 倍。<br>" +
      "第一年成長 ≈ " + money(s.startAssets) + " × " +
      (1 + s.effectiveReturn).toFixed(3) + " ＝ " +
      money(s.startAssets * (1 + s.effectiveReturn)) + "（再加當年投入）。<br>" +
      "「名目市場曝險 " + money(s.marketExposure) +
      "」是跟隨市場的規模，<b>不是帳戶餘額</b>，不可用它乘報酬率。"
    );
  }

  function renderResults() {
    const s = simulate(state);
    const box = document.querySelector("[" + PANEL_FLAG + "] [data-retire-results]");
    if (box) box.innerHTML = resultsHtml(s);
    const order = document.querySelector("[" + PANEL_FLAG + "] [data-retire-order]");
    if (order) order.innerHTML = orderHtml(s);
  }

  function render() {
    const panel = ourPanel();
    if (!panel) return;
    const s = simulate(state);

    const loanRows = (state.loans || [])
      .map(
        (l, i) =>
          '<div class="retire-loan">' +
          '<div class="retire-field"><label>貸款金額</label><input type="text" inputmode="numeric" autocomplete="off" data-money="1" step="10000" data-loan="' +
          i + '" data-lk="amount" value="' + group(l.amount) + '"></div>' +
          '<div class="retire-field"><label>年利率 %</label><input type="number" inputmode="decimal" autocomplete="off" step="0.1" data-loan="' +
          i + '" data-lk="rate" value="' + l.rate + '"></div>' +
          '<div class="retire-field"><label>期數（月）</label><input type="number" inputmode="decimal" autocomplete="off" step="12" data-loan="' +
          i + '" data-lk="months" value="' + l.months + '"></div>' +
          '<div class="retire-field"><label>幾歲開始貸</label><input type="number" inputmode="decimal" autocomplete="off" step="1" data-loan="' +
          i + '" data-lk="startAge" value="' + (l.startAge ?? state.age) + '"></div>' +
          '<button type="button" class="del" data-del="' + i + '">刪除</button></div>',
      )
      .join("");


    panel.innerHTML =
      '<div class="retire-head"><h2>退休計算機</h2>' +
      '<span class="meta">所有結果由你輸入的假設推導，非預測</span></div>' +
      '<div class="retire-grid">' +
      field("age", "目前年齡", "歲") +
      field("portfolio", "現有股票價值", "元（自有資金）") +
      field("cashReserve", "現金儲備", "元；股票以外的現金水位") +
      field("monthlyExpense", "每月基本支出", "元") +
      field("monthlySurplus", "每月盈餘（扣支出後）", "元") +
      field("monthlyInvest", "每月可投入金額", "元；有貸款時會先扣掉月付金") +
      field("investUntilAge", "可投入到幾歲", "歲；之後視為沒有工作收入，停止投入") +
      field("annualReturn", "預期年化報酬 %", REF_HINT) +
      field("withdrawRate", "提領率 %", "常見為 4%") +
      field("withdrawStartAge", "幾歲開始提領", "歲；從這年起每月自資產提出並累計") +
      field("retireAgeCap", "試算到幾歲", "歲") +
      "</div>" +
      '<div class="retire-sub">貸款（可多筆）<button type="button" data-add="1">＋ 新增一筆</button></div>' +
      '<div class="hint" style="color:#8b98ab;font-size:12.5px;font-weight:700;margin:-4px 0 10px;line-height:1.6">' +
      "當你貸款時，就會將金額投入股市曝險；並將你原本每月可投入金額扣除貸款的每月還款金額。" +
      "「幾歲開始貸」填目前年齡代表現在就貸；填未來的年齡，本金會在那一年才撥入股市，" +
      "還款也從那時才開始扣，在那之前不計入負債。</div>" +
      (loanRows || '<div class="hint" style="color:#8b98ab;font-size:12.5px">目前沒有貸款，可直接看純自有資金的結果。</div>') +
      '<div class="retire-sub">股市曝險（在上面的本金之上再放大）</div>' +
      '<div class="retire-grid" style="margin-top:0">' +
      field("targetExposure", "股市曝險 %", EXPOSURE_HINT) +
      // 這段會隨輸入變動，必須放在會即時重算的容器裡，否則會停在舊值。
      '<div class="retire-field"><label>計算順序</label>' +
      '<div class="hint" style="margin-top:6px" data-retire-order></div></div>' +
      "</div>" +
      '<div data-retire-results></div>';
    renderResults();
  }

  function ensure() {
    const host = shell();
    const bar = strip();
    if (!host || !bar) return false;
    style();
    if (!ourTab()) {
      const model = bar.querySelector("button, [role='tab']");
      const tab = document.createElement(model ? model.tagName : "button");
      // 複製樣板分頁的 class 取得一致外觀，但必須去掉「選中」狀態：
      // 樣板剛好是當前分頁時會把 is-active 一起帶進來，讓底線變成看運氣。
      if (model) {
        tab.className = model.className;
        tab.classList.remove("is-active", "is-on", "active");
      }
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute(TAB_FLAG, "");
      tab.textContent = TAB_LABEL;
      tab.addEventListener("click", activate);
      bar.appendChild(tab); // 一律 append，不插入 React 既有子節點之間
    }
    if (!ourPanel()) {
      const panel = document.createElement("section");
      panel.setAttribute(PANEL_FLAG, "");
      panel.className = "retire-panel";
      panel.style.display = "none";
      host.appendChild(panel);
    }
    return true;
  }

  const URL_TAB = "retirement";

  function writeUrl(on) {
    try {
      const url = new URL(window.location.href);
      if (on) url.searchParams.set("tab", URL_TAB);
      else if (url.searchParams.get("tab") === URL_TAB) url.searchParams.delete("tab");
      if (url.href !== window.location.href) {
        window.history.replaceState(window.history.state, "", url);
      }
    } catch (error) {
      /* 網址同步失敗不該影響試算 */
    }
  }

  function syncUrl(on) {
    // 站台本身的 popostock-url-state.js 也在寫網址，它會在 React 分頁狀態
    // 變動後把 tab 改回自己認得的值。我們的分頁不在它的清單裡，所以先寫一次、
    // 再於它跑完後補寫，確保最後停在 tab=retirement。
    writeUrl(on);
    if (on) {
      [80, 300, 800].forEach((delay) =>
        setTimeout(() => { if (active) writeUrl(true); }, delay),
      );
    }
  }

  function activate() {
    if (!ensure()) return;
    active = true;
    syncUrl(true);
    reactPanels().forEach((node) => {
      if (node.dataset.retireHidden === undefined) {
        node.dataset.retireHidden = node.style.display || "";
      }
      node.style.display = "none";
    });
    const panel = ourPanel();
    panel.style.display = "";
    const tab = ourTab();
    if (tab) {
      tab.setAttribute("aria-selected", "true");
      tab.classList.add("is-active");
    }
    strip().querySelectorAll("[role='tab']").forEach((b) => {
      if (b.hasAttribute(TAB_FLAG)) return;
      b.setAttribute("aria-selected", "false");
      // React 的選中樣式靠 class，不是 aria；不移除的話會同時亮兩個分頁。
      if (b.classList.contains("is-active")) {
        b.dataset.retireWasActive = "1";
        b.classList.remove("is-active");
      }
    });
    render();
  }

  function deactivate() {
    active = false;
    syncUrl(false);
    const panel = ourPanel();
    if (panel) panel.style.display = "none";
    reactPanels().forEach((node) => {
      if (node.dataset.retireHidden !== undefined) {
        node.style.display = node.dataset.retireHidden;
        delete node.dataset.retireHidden;
      }
    });
    const tab = ourTab();
    if (tab) {
      tab.setAttribute("aria-selected", "false");
      tab.classList.remove("is-active");
    }
    // 把先前被我們取消的 React 分頁樣式還原。
    const bar = strip();
    if (bar) {
      bar.querySelectorAll("[data-retire-was-active]").forEach((b) => {
        b.classList.add("is-active");
        delete b.dataset.retireWasActive;
      });
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest?.(".workspace-tabs [role='tab']");
      if (!button || button.hasAttribute(TAB_FLAG)) return;
      if (active) deactivate();
    },
    true,
  );

  document.addEventListener("click", (event) => {
    if (!active) return;
    const add = event.target.closest("[" + PANEL_FLAG + "] [data-add]");
    if (add) {
      state.loans = [...(state.loans || []), { amount: 0, rate: 3, months: 84, startAge: Number(state.age || 0) }];
      save(); render(); return;
    }
    const del = event.target.closest("[" + PANEL_FLAG + "] [data-del]");
    if (del) {
      state.loans.splice(Number(del.dataset.del), 1);
      save(); render();
    }
  });

  // text 欄位沒有原生的上下鍵微調，這裡補上，級距沿用 STEP。
  document.addEventListener("keydown", (event) => {
    if (!active) return;
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const input = event.target.closest?.("[" + PANEL_FLAG + "] input[data-money]");
    if (!input) return;
    event.preventDefault();
    const step = Number(input.getAttribute("step")) || 1;
    const current = Number(ungroup(input.value)) || 0;
    const next = Math.max(0, current + (event.key === "ArrowUp" ? step : -step));
    input.value = group(next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  document.addEventListener("input", (event) => {
    if (!active) return;
    const input = event.target.closest("[" + PANEL_FLAG + "] input");
    if (!input) return;
    // 允許中途輸入「」「1,000」「3.」這類還不是合法數字的字串：
    // 清成空字串視為 0 參與試算，但不覆寫使用者正在打的內容。
    const raw = ungroup(input.value);
    const value = raw === "" || raw === "-" || raw === "." ? 0 : Number(raw);
    if (!isFinite(value)) return;
    if (input.dataset.money) {
      // 重新加上千分位後，游標要停在「同樣多的數字之後」，否則會跳到字尾。
      const caret = input.selectionStart ?? input.value.length;
      const digitsBefore = ungroup(input.value.slice(0, caret)).length;
      const formatted = group(raw === "" ? "" : value);
      if (formatted !== input.value) {
        input.value = formatted;
        let seen = 0;
        let pos = formatted.length;
        for (let i = 0; i < formatted.length; i += 1) {
          if (formatted[i] !== ",") seen += 1;
          if (seen === digitsBefore) { pos = i + 1; break; }
        }
        if (digitsBefore === 0) pos = 0;
        input.setSelectionRange(pos, pos);
      }
    }
    if (input.dataset.key) state[input.dataset.key] = value;
    else if (input.dataset.loan !== undefined) {
      state.loans[Number(input.dataset.loan)][input.dataset.lk] = value;
    }
    save();
    // 只重算結果區，表單與游標完全不受影響。
    renderResults();
  });


  function boot() {
    state = load();
    ensure();
    let queued = false;
    const schedule = () => {
      if (queued) return;
      queued = true;
      setTimeout(() => {
        queued = false;
        ensure();
        // 只有在自己的內容被 React 清掉時才整個重建。
        // 少了這個判斷，renderResults() 改 DOM 會觸發本 observer，
        // observer 再呼叫 render() 重建表單，使用者打字時焦點就會被踢掉。
        const panel = ourPanel();
        if (active && panel && !panel.querySelector("[data-retire-results]")) render();
        // React 重繪分頁列後，我們的選中樣式會被沖掉，要補回來。
        const tab = ourTab();
        if (active && tab && !tab.classList.contains("is-active")) {
          tab.classList.add("is-active");
        }
      }, 60);
    };
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      ensure();
      // 直接用 ?tab=retirement 進站時自動切到本頁。
      if (ourTab()) {
        try {
          if (!active && new URL(window.location.href).searchParams.get("tab") === URL_TAB) {
            activate();
          }
        } catch (error) {
          /* 忽略網址解析錯誤 */
        }
        clearInterval(timer);
      } else if (attempts >= 40) {
        clearInterval(timer);
      }
    }, 500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
