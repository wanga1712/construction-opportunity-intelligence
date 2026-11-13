"""Visual language for the commercial dossier workspace."""

MARKET_CSS = """
<style>
:root{
  --crm-ink:#111315;--crm-panel:#171a1c;--crm-panel2:#1e2020;
  --crm-beige:#d8c7a3;--crm-beige-soft:#eee4cf;--crm-muted:#8f918b;
  --crm-line:#343736;--crm-copper:#b76d4d;--crm-cyan:#7ca5a3;--crm-paper:#e9dfcb;
}
[data-testid="stAppViewContainer"],.stApp{background:
  radial-gradient(circle at 18% 8%,rgba(183,109,77,.10),transparent 28rem),
  radial-gradient(circle at 86% 90%,rgba(124,165,163,.08),transparent 30rem),
  #111315;color:var(--crm-beige-soft)}
[data-testid="stHeader"]{background:rgba(17,19,21,.86)}
[data-testid="stSidebar"]{background:#0d0f10;border-right:1px solid #2a2d2c}
[data-testid="stSidebar"] [data-testid="stButton"] button{background:#e9dfcb;color:#181a19;
  border:1px solid #c9bda6;border-radius:2px;font-size:12px}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"]{background:#9b694e;
  color:#fff4df;border-color:#b77a5e}
.block-container{max-width:none;padding:.7rem 1.1rem 1rem}
.crm-market-top{display:flex;align-items:end;justify-content:space-between;gap:18px;
  padding:8px 2px 14px;border-bottom:1px solid var(--crm-line);margin-bottom:12px}
.crm-market-brand{font-family:Georgia,'Times New Roman',serif;font-size:28px;letter-spacing:.02em}
.crm-market-brand small{display:block;font-family:Consolas,monospace;font-size:9px;
  letter-spacing:.22em;color:var(--crm-muted);margin-top:2px}
.crm-market-count{font-family:Consolas,monospace;color:var(--crm-muted);font-size:11px;text-align:right}
div[data-testid="stTextInput"] input{background:#e9dfcb;color:#171a1c;border:1px solid #58554d;
  border-radius:2px;font-family:Georgia,serif;font-size:17px;min-height:46px}
div[data-testid="stTextInput"] input::placeholder{color:#736d61}
.crm-market-top+.stTextInput input{box-shadow:0 2px 14px rgba(0,0,0,.14)}
.crm-zone-title{font-family:Consolas,monospace;letter-spacing:.18em;text-transform:uppercase;
  color:var(--crm-beige);font-size:10px;padding:4px 0 8px;border-bottom:1px solid #2c2f2e;margin-bottom:10px}
.st-key-market_left,.st-key-market_list,.st-key-market_right{border-top:1px solid #494b46;
  padding-top:12px;min-height:0}
.st-key-market_left{padding-right:12px}.st-key-market_list{padding:12px 14px 0;
  border-left:1px solid #2b2e2d;border-right:1px solid #2b2e2d}
.st-key-market_right{padding-left:16px}
.crm-filter-label{font-family:Consolas,monospace;color:#9b9c95;font-size:9px;
  letter-spacing:.15em;text-transform:uppercase;margin:10px 0 3px}
.crm-system-list{display:grid;gap:4px;margin-top:10px}
.crm-system-row{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid #2a2d2c;
  padding:7px 2px;color:#bdb8aa;font-size:12px}
.crm-system-row b{font-family:Consolas,monospace;color:var(--crm-beige)}
div[class*="st-key-market_object_"]{background:#e9dfcb;color:#181a19;border:1px solid #c9bda6;
  border-left:3px solid #9b694e;border-radius:2px;padding:8px 10px 4px;margin:0 0 8px}
div[class*="st-key-market_object_"] button{font-family:Georgia,'Times New Roman',serif!important;
  font-size:15px!important;line-height:1.2!important;text-align:left!important;min-height:42px}
div[class*="st-key-market_object_"] [data-testid="stCaptionContainer"]{color:#645c4f;font-size:10px}
div[class*="st-key-market_object_"] [data-testid="stHorizontalBlock"]{align-items:center}
.st-key-market_card_scroll{overflow-y:auto;overscroll-behavior:contain;
  scrollbar-color:#7a604d #191c1d;scrollbar-width:thin}
.crm-list-empty{background:#171a1c;border:1px dashed #3c3f3d;padding:22px;color:#aaa79d;
  font-family:Georgia,serif;text-align:center}
.crm-dossier-head{background:var(--crm-paper);color:#181a19;padding:14px 15px 12px;
  border-top:4px solid #292c2b;border-bottom:1px solid #c4b79f}
.crm-dossier-kicker{font-family:Consolas,monospace;font-size:9px;letter-spacing:.19em;
  color:#756d5e;text-transform:uppercase}.crm-dossier-title{font-family:Georgia,serif;
  font-size:20px;line-height:1.2;margin:5px 0 7px}.crm-dossier-sub{font-family:Consolas,monospace;
  font-size:10px;color:#6a6254}.crm-dossier-state{display:inline-block;border:1px solid #7f715c;
  padding:2px 7px;margin-right:6px;font-family:Consolas,monospace;font-size:9px;letter-spacing:.08em}
.crm-dossier-tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #3a3d3b;
  padding:9px 0 8px}
.crm-tab-pill{font-family:Consolas,monospace;font-size:9px;letter-spacing:.05em;color:#9a9b94;
  border:1px solid #343735;background:#191c1d;padding:5px 7px;border-radius:2px}
.crm-panel-card{background:#e9dfcb;color:#181a19;border:1px solid #c9bda6;padding:12px;
  margin:7px 0}.crm-panel-card.dark{background:#171a1c;color:#d8c7a3;border-color:#333735}
.crm-panel-label{font-family:Consolas,monospace;text-transform:uppercase;letter-spacing:.14em;
  font-size:9px;color:#7b735f;margin-bottom:5px}.crm-kpi-row{display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.crm-kpi{background:#ded1ba;
  border-left:3px solid #9b694e;padding:8px}.crm-kpi b{display:block;font-family:Georgia,serif;
  font-size:17px}.crm-kpi span{font-size:9px;color:#6f6554}.crm-line{display:flex;
  justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid #cbbfa8;
  font-size:11px}.crm-line:last-child{border-bottom:0}.crm-line span{color:#6d6455}
.crm-line b{font-family:Consolas,monospace;text-align:right}
.crm-category-card{border:1px solid #c7baa2;background:#e9dfcb;padding:10px;margin:7px 0}
.crm-category-title{font-family:Georgia,serif;color:#171918;font-size:16px;font-weight:700}
.crm-category-sub{font-family:Consolas,monospace;color:#786f5f;font-size:9px;margin-top:3px}
.crm-value-trace{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;padding-top:7px;
  border-top:1px solid #cdbfa7;font-size:10px;color:#5e5547}
.crm-value-trace b{color:#221f1a}
.crm-tech-note{font-family:Consolas,monospace;font-size:9px;color:#7b766a;margin-top:4px}
.crm-loader{display:grid;grid-template-columns:180px minmax(0,1fr);gap:20px;align-items:center;
  background:#151819;border:1px solid #373a38;padding:18px;margin:18px 0;min-height:180px}
.crm-loader-visual svg{width:180px;height:118px;display:block}
.crm-loader-copy{display:grid;gap:6px}.crm-loader-kicker{font-family:Consolas,monospace;
  font-size:9px;letter-spacing:.2em;color:#807a6d}.crm-loader-copy strong{font-family:Georgia,serif;
  font-size:22px;color:var(--crm-beige);font-weight:500}.crm-loader-line{display:flex;gap:5px}
.crm-loader-line i{width:30px;height:2px;background:#b76d4d;display:block;animation:cpulse 1.2s infinite}
.crm-loader-line i:nth-child(2){animation-delay:.16s;background:#7ca5a3}
.crm-loader-line i:nth-child(3){animation-delay:.32s;background:#d8c7a3}
@keyframes cpulse{0%,100%{opacity:.2;transform:scaleX(.6)}50%{opacity:1;transform:scaleX(1)}}
.crm-radio [data-testid="stRadio"] label span{font-family:Consolas,monospace;font-size:9px}
.st-key-market_right [data-testid="stRadio"] [role="radiogroup"]{display:flex;gap:5px;flex-wrap:wrap}
.st-key-market_right [data-testid="stRadio"] label{background:#191c1d;border:1px solid #343735;
  border-radius:2px;padding:5px 7px;min-height:0}
.st-key-market_right [data-testid="stRadio"] label>div:first-child{display:none}
.st-key-market_right [data-testid="stRadio"] label p{font-family:Consolas,monospace!important;
  font-size:9px!important;color:#b4aa95!important;line-height:1.15!important}
.st-key-market_right [data-testid="stRadio"] label:has(input:checked){border-color:var(--crm-copper);
  background:#2a211d}
div[data-testid="stButton"] button{border-radius:2px;background:#e9dfcb;color:#1b1d1c;
  border:1px solid #b7aa93;font-family:Consolas,monospace;font-size:10px}
div[data-testid="stButton"] button:hover{border-color:#b76d4d}
.crm-muted{color:var(--crm-muted);font-size:10px}
@media(max-width:1500px){
  .crm-dossier-title{font-size:17px}.crm-loader{grid-template-columns:145px minmax(0,1fr)}
  .crm-loader-visual svg{width:145px;height:96px}
  div[class*="st-key-market_object_"] button{font-size:13px!important}
}
@media(max-width:1200px){
  .block-container{padding:.5rem}.crm-list-panel{padding:0 7px}.crm-dossier-panel{padding-left:8px}
  .crm-kpi-row{grid-template-columns:1fr 1fr}
}
@media(max-height:850px){.st-key-market_card_scroll{height:430px!important}}
@media(min-height:851px){.st-key-market_card_scroll{height:calc(100vh - 385px)!important}}
@media(max-width:1100px){
  .crm-market-brand{font-size:22px}.crm-market-brand small{font-size:8px}
  .crm-dossier-tabs{gap:3px}.crm-panel-card{padding:8px}
  .crm-kpi-row{grid-template-columns:1fr 1fr}
}
</style>
"""
