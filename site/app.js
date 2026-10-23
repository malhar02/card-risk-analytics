(function () {
  "use strict";
  const state = { data:null, page:"overview", threshold:.8, selectedHour:null, selectedDecile:1, selectedStatus:"all", tableKey:"summary", sortKey:null, sortDirection:1, tableQuery:"", toastTimer:null };
  const tableDefinitions = {
    summary:{ description:"Independent holdout and test summaries. Rows are not combined across risk tracks.", fields:[["risk_domain","Risk track"],["sample_name","Evaluation sample"],["records","Rows"],["observed_events","Observed events"],["review_alerts","Review queue"],["precision","Precision"],["recall","Capture rate"],["observed_event_rate","Event rate"],["review_rate","Review rate"],["pr_auc","PR AUC"],["roc_auc","ROC AUC"]] },
    thresholds:{ description:"Validation-only cutoff comparison used to select 0.80 before one final holdout evaluation.", fields:[["threshold","Cutoff"],["alerts","Review alerts"],["true_positives","Fraud found"],["false_positives","Non-fraud alerts"],["false_negatives","Fraud missed"],["precision","Precision"],["recall","Recall"]] },
    deciles:{ description:"Test accounts ranked by model score; decile 1 is the highest-score group.", fields:[["risk_decile","Risk decile"],["account_count","Accounts"],["default_count","Defaults"],["observed_default_rate","Observed default rate"],["average_risk_score","Average score"],["reviewed_account_count","In review"]] },
    paymentStatus:{ description:"Test sample breakdown by PAY_0, the latest repayment status code in this source.", fields:[["latest_payment_status_code","PAY_0 status"],["account_count","Accounts"],["default_count","Defaults"],["observed_default_rate","Observed default rate"],["average_risk_score","Average score"],["reviewed_account_count","In review"]] },
    hourly:{ description:"Holdout activity by elapsed dataset hour; this is not calendar time.", fields:[["elapsed_dataset_hour","Elapsed hour"],["transaction_count","Transactions"],["fraud_count","Fraud labels"],["alert_count","Alerts"],["captured_fraud_count","Fraud captured"],["average_fraud_score","Average score"],["total_amount","Total amount"]] }
  };
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  const n = value => Number(value || 0);
  const number = (value, digits) => new Intl.NumberFormat("en-US",{maximumFractionDigits:digits === undefined ? 0 : digits,minimumFractionDigits:digits === undefined ? 0 : digits}).format(n(value));
  const pct = (value, digits) => (n(value) * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  const money = value => "$" + new Intl.NumberFormat("en-US",{maximumFractionDigits:0}).format(n(value));
  const byNumber = (rows,key) => rows.slice().sort((a,b) => n(a[key]) - n(b[key]));

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }
  function showToast(message) {
    const toast = $("#toast");
    toast.textContent = message; toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("show"),2500);
  }
  function findSummary(name) { return state.data.summary.find(row => row.risk_domain === name); }
  function metricCard(label,value,foot,tone,icon) {
    return '<article class="metric-card metric-' + tone + '"><div class="metric-label"><span>' + escapeHtml(label) + '</span><span class="metric-icon">' + icon + '</span></div><strong class="metric-value">' + escapeHtml(value) + '</strong><div class="metric-foot">' + escapeHtml(foot) + "</div></article>";
  }
  function resultChip(label,value) { return '<div class="result-chip"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + "</strong></div>"; }
  function setPage(page) {
    state.page = page;
    $$(".nav-item").forEach(button => {
      const active = button.dataset.page === page;
      button.classList.toggle("active",active);
      if (active) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current");
    });
    $$(".page-view").forEach(view => {
      const active = view.id === "page-" + page;
      view.classList.toggle("active",active); view.hidden = !active;
    });
    const labels = { overview:"OVERVIEW", fraud:"FRAUD OPERATIONS", credit:"CREDIT PORTFOLIO", methodology:"METHODOLOGY" };
    $("#breadcrumbCurrent").textContent = labels[page] || "OVERVIEW";
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function drawAxes(width,height,margin,maxValue,ticks,labelFormatter) {
    const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom;
    let out = "";
    ticks.forEach(tick => {
      const y = margin.top + plotH - (tick / maxValue) * plotH;
      out += '<line class="chart-grid" x1="' + margin.left + '" y1="' + y + '" x2="' + (width - margin.right) + '" y2="' + y + '"></line><text class="chart-axis" x="' + (margin.left - 9) + '" y="' + (y + 3) + '" text-anchor="end">' + labelFormatter(tick) + "</text>";
    });
    return out;
  }
  function lineChart(rows,config) {
    const width=config.width,height=config.height,margin=config.margin || {top:14,right:24,bottom:30,left:44},maxY=config.maxY;
    const plotW=width-margin.left-margin.right,plotH=height-margin.top-margin.bottom;
    const x=index=>margin.left+(rows.length<2?plotW/2:index*plotW/(rows.length-1));
    const y=value=>margin.top+plotH-(value/maxY)*plotH;
    let out=drawAxes(width,height,margin,maxY,config.ticks,config.yLabel);
    if(config.selectedX !== undefined && config.selectedX !== null) {
      const index=rows.findIndex(row=>Math.abs(n(row[config.xKey])-n(config.selectedX))<.0001);
      if(index>=0) out+='<line class="selected-guide" x1="'+x(index)+'" y1="'+margin.top+'" x2="'+x(index)+'" y2="'+(height-margin.bottom)+'"></line>';
    }
    config.series.forEach(series=>{
      const path=rows.map((row,index)=>(index?"L":"M")+x(index).toFixed(2)+" "+y(n(row[series.key])).toFixed(2)).join(" ");
      out+='<path class="'+series.pathClass+'" d="'+path+'"></path>';
      rows.forEach((row,index)=>{
        const selected=config.selectedX!==undefined && Math.abs(n(row[config.xKey])-n(config.selectedX))<.0001;
        const title=series.label+": "+(series.percent?pct(row[series.key],1):number(row[series.key]));
        out+='<circle class="chart-dot '+series.dotClass+'" cx="'+x(index)+'" cy="'+y(n(row[series.key]))+'" r="'+(selected?5:3.5)+'" tabindex="0" data-x="'+escapeHtml(row[config.xKey])+'" fill="'+series.color+'"><title>'+escapeHtml(title)+"</title></circle>";
      });
    });
    rows.forEach((row,index)=>{out+='<text class="chart-axis" x="'+x(index)+'" y="'+(height-margin.bottom+16)+'" text-anchor="middle">'+escapeHtml(config.xLabel(row))+"</text>";});
    if(config.xTitle) out+='<text class="chart-axis-title" x="'+(width/2)+'" y="'+(height-2)+'" text-anchor="middle">'+escapeHtml(config.xTitle)+"</text>";
    return out;
  }
  function renderThresholdChart(elementId,selected,width,height) {
    const rows=byNumber(state.data.thresholds,"threshold"),selectedRow=rows.find(row=>Math.abs(n(row.threshold)-selected)<.0001),svg=$("#"+elementId);
    if(!svg) return;
    svg.innerHTML=lineChart(rows,{width:width,height:height,maxY:1,ticks:[0,.25,.5,.75,1],margin:{top:18,right:24,bottom:31,left:43},xKey:"threshold",selectedX:selected,yLabel:value=>Math.round(value*100)+"%",xLabel:row=>n(row.threshold).toFixed(1),xTitle:"Fraud score cutoff (validation)",series:[{key:"recall",label:"Recall",pathClass:"chart-path-blue",dotClass:"threshold-point",color:"#3977d5",percent:true},{key:"precision",label:"Precision",pathClass:"chart-path-coral",dotClass:"threshold-point",color:"#db6870",percent:true}]});
    svg.setAttribute("viewBox","0 0 "+width+" "+height);
    svg.querySelectorAll(".threshold-point").forEach(point=>{
      point.addEventListener("click",()=>updateThreshold(n(point.dataset.x)));
      point.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")updateThreshold(n(point.dataset.x));});
    });
    if(elementId==="fraudThresholdChart") updateThresholdDetail(selectedRow);
  }
  function updateThreshold(value) {
    state.threshold=Math.max(.1,Math.min(.9,Math.round(value*10)/10));
    const slider=$("#thresholdRange"); if(slider) slider.value=String(Math.round(state.threshold*100));
    $("#thresholdValue").textContent=state.threshold.toFixed(2);
    renderThresholdChart("fraudThresholdChart",state.threshold,900,260);
    renderThresholdChart("overviewThresholdChart",.8,720,230);
  }
  function updateThresholdDetail(row) {
    if(!row) return;
    $("#thresholdStats").innerHTML='<div class="threshold-stat"><span>Validation alerts</span><strong>'+number(row.alerts)+'</strong></div><div class="threshold-stat"><span>Fraud captured</span><strong>'+number(row.true_positives)+'</strong></div><div class="threshold-stat"><span>Non-fraud alerts</span><strong>'+number(row.false_positives)+'</strong></div><div class="threshold-stat"><span>Precision</span><strong>'+pct(row.precision,1)+'</strong></div><div class="threshold-stat"><span>Recall</span><strong>'+pct(row.recall,1)+'</strong></div>';
  }
  function renderDecileChart(elementId,selected,width,height) {
    const rows=byNumber(state.data.deciles,"risk_decile"),svg=$("#"+elementId);
    if(!svg) return;
    const margin={top:17,right:24,bottom:30,left:43},maxY=.8,plotW=width-margin.left-margin.right,plotH=height-margin.top-margin.bottom,band=plotW/rows.length,barW=Math.min(31,band*.55);
    let out=drawAxes(width,height,margin,maxY,[0,.2,.4,.6,.8],value=>Math.round(value*100)+"%");
    [0,.2,.4,.6,.8].forEach(score=>{const y=margin.top+plotH-(score/.8)*plotH;out+='<text class="chart-axis" x="'+(width-2)+'" y="'+(y+3)+'" text-anchor="end">'+score.toFixed(1)+"</text>";});
    const scorePath=[];
    rows.forEach((row,index)=>{
      const center=margin.left+(index+.5)*band,isSelected=n(row.risk_decile)===selected,barH=n(row.observed_default_rate)/maxY*plotH,barY=margin.top+plotH-barH;
      out+='<rect class="chart-bar teal-bar'+(isSelected?" selected":"")+'" x="'+(center-barW/2)+'" y="'+barY+'" width="'+barW+'" height="'+barH+'" rx="4" data-decile="'+row.risk_decile+'" tabindex="0"><title>Decile '+row.risk_decile+": "+pct(row.observed_default_rate,1)+" observed default rate · "+number(row.default_count)+" defaults of "+number(row.account_count)+" accounts</title></rect>";
      out+='<text class="chart-axis" x="'+center+'" y="'+(height-margin.bottom+15)+'" text-anchor="middle">'+number(row.risk_decile)+"</text>";
      const scoreY=margin.top+plotH-(n(row.average_risk_score)/.8)*plotH;
      scorePath.push((index?"L":"M")+center.toFixed(2)+" "+scoreY.toFixed(2));
    });
    out+='<path class="chart-path-muted" d="'+scorePath.join(" ")+'"></path>';
    rows.forEach((row,index)=>{const center=margin.left+(index+.5)*band,scoreY=margin.top+plotH-(n(row.average_risk_score)/.8)*plotH;out+='<circle class="chart-dot" cx="'+center+'" cy="'+scoreY+'" r="3" fill="#588fcb"><title>Decile '+row.risk_decile+": average score "+n(row.average_risk_score).toFixed(3)+"</title></circle>";});
    out+='<text class="chart-axis-title" x="'+(width/2)+'" y="'+(height-2)+'" text-anchor="middle">Risk decile (1 = highest score)</text>';
    svg.innerHTML=out; svg.setAttribute("viewBox","0 0 "+width+" "+height);
    svg.querySelectorAll("[data-decile]").forEach(bar=>{bar.addEventListener("click",()=>updateDecile(Number(bar.dataset.decile)));bar.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")updateDecile(Number(bar.dataset.decile));});});
  }
  function updateDecile(decile) {
    state.selectedDecile=decile;
    renderDecileChart("creditDecileChart",decile,900,260);
    renderDecileChart("overviewDecileChart",1,720,230);
    const row=state.data.deciles.find(item=>n(item.risk_decile)===decile);
    if(row) $("#decileDetail").innerHTML="<strong>Decile "+number(row.risk_decile)+"</strong> · "+number(row.account_count)+" test accounts · "+number(row.default_count)+" observed defaults ("+pct(row.observed_default_rate,1)+") · average score "+n(row.average_risk_score).toFixed(3)+" · "+number(row.reviewed_account_count)+" accounts in the hypothetical queue.";
  }
  function renderHourlyChart() {
    const svg=$("#fraudHourlyChart"),rows=byNumber(state.data.hourly,"elapsed_dataset_hour"),width=1000,height=270,margin={top:18,right:30,bottom:34,left:50};
    const plotW=width-margin.left-margin.right,plotH=height-margin.top-margin.bottom,maxTx=Math.ceil(Math.max.apply(null,rows.map(row=>n(row.transaction_count)))/2000)*2000,maxFraud=Math.max(4,Math.ceil(Math.max.apply(null,rows.map(row=>n(row.fraud_count)))/5)*5),band=plotW/rows.length,barW=band*.54;
    let out=drawAxes(width,height,margin,maxTx,[0,maxTx/4,maxTx/2,maxTx*.75,maxTx],number),fraudLine=[];
    [0,.25,.5,.75,1].forEach(fraction=>{const y=margin.top+plotH-fraction*plotH;out+='<text class="chart-axis" x="'+(width-2)+'" y="'+(y+3)+'" text-anchor="end">'+Math.round(fraction*maxFraud)+"</text>";});
    rows.forEach((row,index)=>{
      const center=margin.left+(index+.5)*band,isSelected=state.selectedHour!==null&&n(row.elapsed_dataset_hour)===state.selectedHour,barH=n(row.transaction_count)/maxTx*plotH,barY=margin.top+plotH-barH,pointY=margin.top+plotH-(n(row.fraud_count)/maxFraud)*plotH;
      out+='<rect class="chart-bar'+(isSelected?" selected":"")+'" x="'+(center-barW/2)+'" y="'+barY+'" width="'+barW+'" height="'+barH+'" rx="3" data-hour="'+row.elapsed_dataset_hour+'" tabindex="0"><title>Elapsed hour '+row.elapsed_dataset_hour+": "+number(row.transaction_count)+" transactions</title></rect>";
      fraudLine.push((index?"L":"M")+center.toFixed(2)+" "+pointY.toFixed(2));
      out+='<text class="chart-axis" x="'+center+'" y="'+(height-margin.bottom+16)+'" text-anchor="middle">'+row.elapsed_dataset_hour+"</text>";
    });
    out+='<path class="chart-path-coral" d="'+fraudLine.join(" ")+'"></path>';
    rows.forEach((row,index)=>{const center=margin.left+(index+.5)*band,pointY=margin.top+plotH-(n(row.fraud_count)/maxFraud)*plotH;out+='<circle class="chart-dot" cx="'+center+'" cy="'+pointY+'" r="3.5" fill="#db6870"><title>Elapsed hour '+row.elapsed_dataset_hour+": "+number(row.fraud_count)+" observed fraud labels</title></circle>";});
    out+='<text class="chart-axis-title" x="'+(width/2)+'" y="'+(height-2)+'" text-anchor="middle">Elapsed dataset hour</text>';
    svg.innerHTML=out; svg.querySelectorAll("[data-hour]").forEach(bar=>{bar.addEventListener("click",()=>updateHour(Number(bar.dataset.hour)));bar.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")updateHour(Number(bar.dataset.hour));});});
    if(state.selectedHour===null&&rows.length) updateHour(n(rows[0].elapsed_dataset_hour),false);
  }
  function updateHour(hour,redraw) {
    state.selectedHour=hour; const row=state.data.hourly.find(item=>n(item.elapsed_dataset_hour)===hour); if(!row)return;
    $("#hourDetail").innerHTML="<strong>Elapsed hour "+number(row.elapsed_dataset_hour)+"</strong> · "+number(row.transaction_count)+" transactions · "+number(row.fraud_count)+" observed fraud labels · "+number(row.alert_count)+" holdout alerts · "+number(row.captured_fraud_count)+" fraud labels captured · total amount "+money(row.total_amount)+".";
    if(redraw!==false) renderHourlyChart();
  }
  function renderPayments() {
    const rows=byNumber(state.data.paymentStatus,"latest_payment_status_code"),maxAccounts=Math.max.apply(null,rows.map(row=>n(row.account_count))),select=$("#paymentStatusSelect");
    select.innerHTML='<option value="all">All statuses</option>'+rows.map(row=>'<option value="'+row.latest_payment_status_code+'">PAY_0 = '+row.latest_payment_status_code+" · "+number(row.account_count)+" accounts</option>").join("");
    select.value=state.selectedStatus;
    $("#paymentBars").innerHTML=rows.map(row=>{
      const code=String(row.latest_payment_status_code),sparse=n(row.account_count)<30,selected=state.selectedStatus===code,width=Math.max(2,n(row.account_count)/maxAccounts*100);
      return '<div class="payment-row'+(sparse?" sparse":"")+(selected?" selected":"")+'" data-status="'+escapeHtml(code)+'" role="listitem" tabindex="0" aria-label="Payment status '+escapeHtml(code)+", "+number(row.account_count)+" accounts, "+pct(row.observed_default_rate,1)+" observed default rate\"><div class=\"payment-label\"><span>PAY_0 = "+escapeHtml(code)+"</span><small>"+number(row.account_count)+'</small></div><div class="payment-track"><div class="payment-fill" style="width:'+width+'%"></div></div><div class="payment-rate">'+pct(row.observed_default_rate,1)+"</div></div>";
    }).join("");
    $("#paymentBars").querySelectorAll("[data-status]").forEach(item=>{
      const choose=()=>{state.selectedStatus=item.dataset.status;renderPayments();};
      item.addEventListener("click",choose); item.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")choose();});
    });
    updatePaymentDetail();
  }
  function updatePaymentDetail() {
    const rows=byNumber(state.data.paymentStatus,"latest_payment_status_code");
    if(state.selectedStatus==="all"){
      const accounts=rows.reduce((sum,row)=>sum+n(row.account_count),0),defaults=rows.reduce((sum,row)=>sum+n(row.default_count),0),reviewed=rows.reduce((sum,row)=>sum+n(row.reviewed_account_count),0);
      $("#paymentDetail").innerHTML='<div class="detail-code">ALL STATUS GROUPS</div><h4>Portfolio baseline</h4><div class="payment-detail-metric"><span>Accounts</span><strong>'+number(accounts)+'</strong></div><div class="payment-detail-metric"><span>Observed defaults</span><strong>'+number(defaults)+" ("+pct(defaults/accounts,1)+')</strong></div><div class="payment-detail-metric"><span>In hypothetical review</span><strong>'+number(reviewed)+'</strong></div><div class="payment-detail-metric"><span>Rate interpretation</span><strong>Observed sample only</strong></div>';
      return;
    }
    const row=rows.find(item=>String(item.latest_payment_status_code)===state.selectedStatus); if(!row)return;
    $("#paymentDetail").innerHTML='<div class="detail-code">LATEST REPAYMENT CODE</div><h4>PAY_0 = '+escapeHtml(state.selectedStatus)+'</h4><div class="payment-detail-metric"><span>Accounts</span><strong>'+number(row.account_count)+'</strong></div><div class="payment-detail-metric"><span>Observed defaults</span><strong>'+number(row.default_count)+'</strong></div><div class="payment-detail-metric"><span>Observed default rate</span><strong>'+pct(row.observed_default_rate,1)+'</strong></div><div class="payment-detail-metric"><span>In hypothetical review</span><strong>'+number(row.reviewed_account_count)+'</strong></div>'+(n(row.account_count)<30?'<div class="payment-detail-metric"><span>Sample size</span><strong style="color:#a4752e">Sparse · interpret carefully</strong></div>':"");
  }
  function formatValue(key,value) {
    if(value===null||value===undefined||value==="")return "—";
    if(["precision","recall","observed_event_rate","review_rate","observed_default_rate"].includes(key))return pct(value,1);
    if(["pr_auc","roc_auc","average_risk_score","average_fraud_score"].includes(key))return n(value).toFixed(3);
    if(key==="threshold")return n(value).toFixed(2);
    if(key==="decision_cutoff")return n(value).toFixed(3);
    if(key==="total_amount")return money(value);
    if(typeof value==="number")return number(value);
    return String(value);
  }
  function renderExplorer() {
    const def=tableDefinitions[state.tableKey]; let rows=(state.data[state.tableKey]||[]).slice(),query=state.tableQuery.trim().toLowerCase();
    if(query)rows=rows.filter(row=>def.fields.some(field=>String(row[field[0]]).toLowerCase().includes(query)));
    if(state.sortKey){
      const key=state.sortKey,direction=state.sortDirection;
      rows.sort((a,b)=>{const av=a[key],bv=b[key];if(typeof av==="number"&&typeof bv==="number")return(av-bv)*direction;return String(av).localeCompare(String(bv))*direction;});
    }
    const header=def.fields.map(([key,label])=>{const sortMark=state.sortKey===key?(state.sortDirection>0?" ↑":" ↓"):"",numeric=!["risk_domain","sample_name","decision_policy"].includes(key);return '<th class="'+(numeric?"numeric":"")+'"><button data-sort="'+escapeHtml(key)+'" title="Sort by '+escapeHtml(label)+'">'+escapeHtml(label+sortMark)+"</button></th>";}).join("");
    $("#explorerTable").querySelector("thead").innerHTML="<tr>"+header+"</tr>";
    $("#explorerTable").querySelector("tbody").innerHTML=rows.length?rows.map(row=>"<tr>"+def.fields.map(([key])=>{const value=formatValue(key,row[key]),cls=key==="risk_domain"?"domain-cell":(!["sample_name","decision_policy"].includes(key)?"numeric":"");return '<td class="'+cls+'" title="'+escapeHtml(String(row[key]))+'">'+escapeHtml(value)+"</td>";}).join("")+"</tr>").join(""):'<tr><td colspan="'+def.fields.length+'">No matching rows.</td></tr>';
    $("#tableDescription").textContent=def.description;
    $("#tableCount").textContent=rows.length+" of "+state.data[state.tableKey].length+" rows · click a column heading to sort";
    $("#explorerTable").querySelectorAll("[data-sort]").forEach(button=>button.addEventListener("click",()=>{const key=button.dataset.sort;state.sortDirection=state.sortKey===key?state.sortDirection*-1:1;state.sortKey=key;renderExplorer();}));
  }
  function exportCsv(rows,fields,filename) {
    const csvCell=value=>'"'+String(value===null||value===undefined?"":value).replace(/"/g,'""')+'"';
    const output=[fields.map(field=>csvCell(field[1])).join(",")].concat(rows.map(row=>fields.map(field=>csvCell(row[field[0]])).join(","))).join("\r\n");
    const blob=new Blob(["\ufeff"+output],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob),link=document.createElement("a");
    link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);showToast("CSV export downloaded");
  }
  function downloadJson() {
    const blob=new Blob([JSON.stringify(state.data,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),link=document.createElement("a");
    link.href=url;link.download="card-risk-dashboard-data.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);showToast("Dashboard data downloaded");
  }
  function renderOverview() {
    const fraud=findSummary("Fraud"),credit=findSummary("Credit Default");
    $("#overviewKpis").innerHTML=metricCard("Fraud · holdout PR AUC",n(fraud.pr_auc).toFixed(3),"85,500 later-time transactions","blue","↗")+metricCard("Fraud · recall at 0.80",pct(fraud.recall,1),number(fraud.true_positives)+" of "+number(fraud.observed_events)+" fraud labels found","coral","⌁")+metricCard("Credit · test PR AUC",n(credit.pr_auc).toFixed(3),"4,464 test accounts","teal","◈")+metricCard("Credit · default capture",pct(credit.recall,1),number(credit.true_positives)+" of "+number(credit.observed_events)+" test defaults","teal","◎")+metricCard("Credit · review rate",pct(credit.review_rate,1),number(credit.review_alerts)+" accounts in review","amber","▤");
    $("#summaryTable tbody").innerHTML=[fraud,credit].map(row=>'<tr><td class="domain-cell"><span class="domain-tag '+(row.risk_domain==="Credit Default"?"credit":"")+'">'+escapeHtml(row.risk_domain)+"</span></td><td>"+escapeHtml(row.sample_name)+"</td><td class=\"numeric\">"+number(row.records)+"</td><td class=\"numeric\">"+number(row.observed_events)+"</td><td class=\"numeric\">"+number(row.review_alerts)+"</td><td class=\"numeric\">"+pct(row.precision,1)+"</td><td class=\"numeric\">"+pct(row.recall,1)+"</td><td class=\"numeric\">"+n(row.pr_auc).toFixed(3)+"</td></tr>").join("");
    $("#analystReadout").textContent="Fraud recall is "+pct(fraud.recall,1)+" at the selected holdout cutoff, with "+number(fraud.false_positives)+" legitimate transactions entering review. The credit queue reviews "+pct(credit.review_rate,1)+" of test accounts and captures "+pct(credit.recall,1)+" of observed defaults. The useful question is how much investigation capacity is available—and what the cost of misses and false alerts is.";
    $("#insightFraudPrecision").textContent=pct(fraud.precision,1);$("#insightCreditCapture").textContent=pct(credit.recall,1);
    const top=byNumber(state.data.deciles,"risk_decile")[0];$("#overviewTopDecile").textContent=pct(top.observed_default_rate,1)+" observed default rate";
    renderThresholdChart("overviewThresholdChart",.8,720,230);renderDecileChart("overviewDecileChart",1,720,230);
  }
  function renderFraud() {
    const row=findSummary("Fraud");
    $("#fraudKpis").innerHTML=metricCard("Holdout transactions",number(row.records),"Latest 30% · time-ordered holdout","blue","▤")+metricCard("Observed fraud labels",number(row.observed_events),pct(row.observed_event_rate,3)+" of holdout","coral","⌁")+metricCard("Review alerts",number(row.review_alerts),pct(row.review_rate,2)+" of holdout transactions","amber","⚑")+metricCard("Fraud captured",pct(row.recall,1),number(row.true_positives)+" true positives","teal","✓")+metricCard("Review precision",pct(row.precision,1),number(row.false_positives)+" non-fraud alerts","coral","!");
    $("#fraudHoldoutStats").innerHTML=resultChip("Precision",pct(row.precision,1))+resultChip("Recall",pct(row.recall,1))+resultChip("PR AUC",n(row.pr_auc).toFixed(3))+resultChip("ROC AUC",n(row.roc_auc).toFixed(3));
    $("#fraudConfusion").innerHTML='<div class="confusion-cell"><span>Fraud found · TP</span><strong>'+number(row.true_positives)+'</strong></div><div class="confusion-cell"><span>Legitimate alert · FP</span><strong>'+number(row.false_positives)+'</strong></div><div class="confusion-cell"><span>Fraud missed · FN</span><strong>'+number(row.false_negatives)+'</strong></div><div class="confusion-cell"><span>Legitimate not flagged · TN</span><strong>'+number(row.records-row.observed_events-row.false_positives)+'</strong></div>';
    renderThresholdChart("fraudThresholdChart",state.threshold,900,260);renderHourlyChart();
  }
  function renderCredit() {
    const row=findSummary("Credit Default");
    $("#creditKpis").innerHTML=metricCard("Test accounts",number(row.records),"Seeded 15% test sample","blue","▤")+metricCard("Observed defaults",number(row.observed_events),pct(row.observed_event_rate,1)+" test-sample rate","amber","◈")+metricCard("Test PR AUC",n(row.pr_auc).toFixed(3),"Precision-recall ranking quality","teal","↗")+metricCard("Defaults captured",pct(row.recall,1),number(row.true_positives)+" defaults in review","teal","✓")+metricCard("Review precision",pct(row.precision,1),number(row.review_alerts)+" accounts in queue","coral","⚑");
    $("#creditQueueRate").textContent=pct(row.review_rate,1);$("#capacityRing").style.background="conic-gradient(#149c8b 0 "+(n(row.review_rate)*100)+"%, #e8eff2 "+(n(row.review_rate)*100)+"% 100%)";
    $("#creditQueueStats").innerHTML='<div class="capacity-kpi"><strong>'+number(row.true_positives)+'</strong><span>defaults captured</span></div><div class="capacity-kpi"><strong>'+number(row.false_negatives)+'</strong><span>defaults outside queue</span></div>';
    renderDecileChart("creditDecileChart",state.selectedDecile,900,260);updateDecile(state.selectedDecile);renderPayments();
  }
  function renderAll() {
    renderOverview();renderFraud();renderCredit();renderExplorer();$("#thresholdRange").value=String(Math.round(state.threshold*100));
  }
  function attachEvents() {
    $$(".nav-item").forEach(button=>button.addEventListener("click",()=>setPage(button.dataset.page)));
    $$("[data-go]").forEach(button=>button.addEventListener("click",()=>setPage(button.dataset.go)));
    $("#thresholdRange").addEventListener("input",event=>updateThreshold(Number(event.target.value)/100));
    $("#paymentStatusSelect").addEventListener("change",event=>{state.selectedStatus=event.target.value;renderPayments();});
    $("#tableDataset").addEventListener("change",event=>{state.tableKey=event.target.value;state.sortKey=null;renderExplorer();});
    $("#tableSearch").addEventListener("input",event=>{state.tableQuery=event.target.value;renderExplorer();});
    $("#downloadTable").addEventListener("click",()=>exportCsv(state.data[state.tableKey]||[],tableDefinitions[state.tableKey].fields,"card-risk-"+state.tableKey+".csv"));
    $("#downloadSummary").addEventListener("click",()=>exportCsv(state.data.summary,tableDefinitions.summary.fields,"card-risk-model-summary.csv"));
    $("#downloadSnapshot").addEventListener("click",downloadJson);
  }
  async function initialize() {
    attachEvents();
    try {
      const response=await fetch("./data/dashboard.json",{cache:"no-store"});
      if(!response.ok)throw new Error("Could not load the dashboard data snapshot.");
      state.data=await response.json();renderAll();
    } catch(error) {
      $("#overviewKpis").innerHTML='<div class="callout callout-warning"><span class="callout-icon">!</span><p><strong>Dashboard data could not be loaded.</strong> Open the site through a local web server or GitHub Pages so the JSON snapshot can be fetched.</p></div>';
      $("#tableCount").textContent=error.message;
    }
  }
  document.addEventListener("DOMContentLoaded",initialize);
})();
