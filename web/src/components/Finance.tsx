import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { lang } from "../i18n";
import type { FinanceInfo, LiveOrder, LiveSettings, LiveStatus, PaperView, Settings } from "../types";

const F = lang === "es"
  ? {
      intro: "Spike Finance usa precios públicos de un exchange (sin clave), hace backtests y calcula el riesgo de una cartera. Para probar estrategias tienes una cuenta simulada (paper trading) con comisiones y deslizamiento.",
      prices: "Exchange para precios", paper: "Cuenta simulada (paper trading)", cash: "Saldo inicial", quote: "Moneda", reset: "Reiniciar cuenta",
      resetAsk: "Se borran las órdenes y el saldo vuelve al inicial.", total: "Valor", pnl: "Resultado", unpriced: "sin precio ahora", noPrice: "No se pudo leer el precio",
      orders: "Órdenes", none: "Todavía no hay órdenes.", cancel: "Cancelar",
      live: "Órdenes reales", liveIntro: "Apagadas por defecto. Si las activas, un especialista solo puede proponer una orden; nada llega al exchange hasta que pulses Confirmar en el chat, y cada orden se vuelve a comprobar con tus límites. Las propuestas caducan a los 10 minutos.",
      enabled: "Permitir proponer órdenes reales", exchange: "Exchange", choose: "elige…", sandbox: "Usar la red de pruebas del exchange (dinero de prueba)",
      testnets: "Red de pruebas disponible en", noWithdrawal: "Confirmo que la clave NO puede retirar fondos (crea en el exchange una clave solo de lectura y trading, sin retiros)",
      maxOrder: "Máximo por orden", maxDay: "Máximo en 24 horas", symbols: "Mercados permitidos (separados por comas)", save: "Guardar", saved: "Guardado",
      key: "API key", secret: "Secreto", saveKey: "Guardar clave", keySaved: "Clave guardada (no se vuelve a mostrar)", noKey: "Sin clave", removeKey: "Borrar clave",
      check: "Probar clave", checkOk: "La clave funciona", withdrawYes: "El exchange dice que esta clave PUEDE retirar fondos: crea otra sin ese permiso",
      withdrawNo: "El exchange confirma que no puede retirar", spent: "Órdenes reales en 24 h", problems: "Ahora no se pueden proponer órdenes reales:", ready: "Listo: cada orden necesitará tu clic",
      realFunds: "Con dinero real", localOnly: "Las claves y estos ajustes solo se cambian desde este ordenador.",
      problem: { off: "Las órdenes reales están apagadas", no_exchange: "No has elegido exchange", no_key: "No hay API key guardada para este exchange",
        withdrawal_unconfirmed: "No has confirmado que la clave no puede retirar fondos", no_testnet: "Este exchange no tiene red de pruebas; quita el modo de pruebas solo si quieres operar con dinero real",
        can_withdraw: "El exchange dice que esta clave puede retirar fondos: crea otra sin ese permiso" } as Record<string, string>,
      status: { proposed: "esperando tu confirmación", sending: "enviando", placed: "enviada", failed: "fallida", cancelled: "cancelada", expired: "caducada", open: "abierta", filled: "ejecutada" } as Record<string, string>,
    }
  : {
      intro: "Spike Finance uses an exchange's public prices (no key), runs backtests and measures a portfolio's risk. To try strategies there is a simulated (paper trading) account with fees and slippage.",
      prices: "Exchange for prices", paper: "Simulated account (paper trading)", cash: "Starting cash", quote: "Currency", reset: "Reset account",
      resetAsk: "Orders are deleted and the balance goes back to the start.", total: "Value", pnl: "Result", unpriced: "no price now", noPrice: "Could not read the price",
      orders: "Orders", none: "No orders yet.", cancel: "Cancel",
      live: "Real orders", liveIntro: "Off by default. If you turn them on, a specialist can only propose an order; nothing reaches the exchange until you click Confirm in the chat, and every order is checked again against your limits. Proposals expire after 10 minutes.",
      enabled: "Allow real orders to be proposed", exchange: "Exchange", choose: "choose…", sandbox: "Use the exchange's test network (test money)",
      testnets: "Test network available on", noWithdrawal: "I confirm the key CANNOT withdraw funds (create a read and trade key on the exchange, without withdrawals)",
      maxOrder: "Maximum per order", maxDay: "Maximum in 24 hours", symbols: "Allowed markets (comma separated)", save: "Save", saved: "Saved",
      key: "API key", secret: "Secret", saveKey: "Save key", keySaved: "Key saved (never shown again)", noKey: "No key", removeKey: "Delete key",
      check: "Test key", checkOk: "The key works", withdrawYes: "The exchange says this key CAN withdraw funds: create one without that permission",
      withdrawNo: "The exchange confirms it cannot withdraw", spent: "Real orders in 24 h", problems: "Real orders cannot be proposed now:", ready: "Ready: every order will need your click",
      realFunds: "Real funds", localOnly: "Keys and these settings can only be changed on this computer.",
      problem: {} as Record<string, string>,
      status: { proposed: "waiting for your confirmation", sending: "sending", placed: "sent", failed: "failed", cancelled: "cancelled", expired: "expired", open: "open", filled: "filled" } as Record<string, string>,
    };

const C = lang === "es"
  ? { title: "Orden real propuesta", test: "red de pruebas", real: "DINERO REAL", about: "aprox.", confirm: "Confirmar", sure: "¿Enviar esta orden a", yes: "Sí, enviar", no: "No",
      cancel: "Cancelar", expires: "caduca en", min: "min", limit: "límite", market: "a mercado", buy: "Comprar", sell: "Vender" }
  : { title: "Proposed real order", test: "test network", real: "REAL FUNDS", about: "about", confirm: "Confirm", sure: "Send this order to", yes: "Yes, send it", no: "No",
      cancel: "Cancel", expires: "expires in", min: "min", limit: "limit", market: "at market", buy: "Buy", sell: "Sell" };

const TTL_S = 600;
const num = (x: number, d = 2) => x.toLocaleString(lang, { maximumFractionDigits: d });

/** The card a `propose_live_order` result shows in the chat: nothing is sent until the user confirms it here. */
export function LiveOrderCard({ initial, readOnly }: { initial: LiveOrder; readOnly?: boolean }) {
  const [order, setOrder] = useState(initial);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => { // the order's current state: it may have been confirmed, cancelled or expired since
    if (!readOnly) api.get<LiveOrder>(`/api/finance/live/orders/${initial.id}`).then(setOrder).catch(() => {});
  }, [initial.id, readOnly]);
  useEffect(() => {
    if (order.status !== "proposed") return;
    const id = setInterval(() => setNow(Date.now() / 1000), 15_000);
    return () => clearInterval(id);
  }, [order.status]);
  const left = Math.max(0, Math.ceil((order.created + TTL_S - now) / 60));
  const act = async (what: "confirm" | "cancel") => {
    setBusy(true); setErr("");
    try {
      const path = `/api/finance/live/orders/${order.id}/${what}`;
      setOrder(what === "confirm" ? await api.post<LiveOrder>(path, { id: order.id }, { "X-Spike-Confirm": order.id }) : await api.post<LiveOrder>(path));
    } catch (e) {
      setErr((e as ApiError).message);
      api.get<LiveOrder>(`/api/finance/live/orders/${order.id}`).then(setOrder).catch(() => {});
    } finally {
      setBusy(false); setAsking(false);
    }
  };
  const open = order.status === "proposed" && left > 0 && !readOnly;
  return (
    <div className={`live-order ${order.sandbox ? "" : "real"}`} role="group" aria-label={C.title}>
      <div className="live-order-head">
        <b>{C.title}</b>
        <span className={`badge ${order.sandbox ? "" : "warn"}`}>{order.sandbox ? C.test : C.real}</span>
        <span className={`badge status-${order.status}`}>{F.status[order.status] ?? order.status}</span>
      </div>
      <div className="live-order-body">
        <span className={`side side-${order.side}`}>{order.side === "buy" ? C.buy : C.sell}</span>{" "}
        <b>{num(order.amount, 8)} {order.symbol.split("/")[0]}</b> · {order.symbol} · {order.exchange} ·{" "}
        {order.type === "limit" && order.price ? `${C.limit} ${num(order.price, 8)}` : C.market} · {C.about} {num(order.notional)} {order.symbol.split("/")[1]}
      </div>
      {order.result && <div className="small muted">{order.result}</div>}
      {open && (
        <div className="permission-actions">
          {asking ? (<>
            <span className="small">{C.sure} {order.exchange}{order.sandbox ? ` (${C.test})` : ` (${C.real})`}?</span>
            <button className="btn primary" disabled={busy} onClick={() => act("confirm")}>{C.yes}</button>
            <button className="btn" disabled={busy} onClick={() => setAsking(false)}>{C.no}</button>
          </>) : (<>
            <button className="btn primary" disabled={busy} onClick={() => setAsking(true)}>{C.confirm}</button>
            <button className="btn danger" disabled={busy} onClick={() => act("cancel")}>{C.cancel}</button>
            <span className="small muted">{C.expires} {left} {C.min}</span>
          </>)}
        </div>
      )}
      {err && <div className="bad small" role="alert">{err}</div>}
    </div>
  );
}

function Paper() {
  const [view, setView] = useState<PaperView | null>(null);
  const [cash, setCash] = useState("10000");
  const [quote, setQuote] = useState("USDT");
  const [err, setErr] = useState("");
  const load = () => api.get<PaperView>("/api/finance/paper").then((v) => { setView(v); setCash(String(v.start.cash)); setQuote(v.start.quote); })
    .catch((e) => setErr(String(e.message)));
  useEffect(() => { load(); }, []);
  const reset = async () => {
    setErr("");
    try { setView(await api.post<PaperView>("/api/finance/paper/reset", { cash: Number(cash), quote })); } catch (e) { setErr(String((e as Error).message)); }
  };
  const cancel = async (id: string) => { await api.post(`/api/finance/paper/orders/${id}/cancel`); load(); };
  if (!view) return err ? <div className="bad small">{err}</div> : null;
  const v = view.valuation;
  return (
    <div className="card">
      <div className="card-head"><b>{F.paper}</b>
        <span className="badge">{F.total}: {num(v.total)} {v.quote}</span>
        {v.pnl !== null && <span className={`badge ${v.pnl >= 0 ? "ok" : "warn"}`}>{F.pnl}: {v.pnl >= 0 ? "+" : ""}{num(v.pnl)} ({v.pnl_pct}%)</span>}
      </div>
      <div className="row">
        {Object.entries(view.balances).filter(([, q]) => q).map(([asset, q]) => (
          <span key={asset} className="chip">{asset} {num(q, 8)}{v.unpriced.includes(asset) ? ` · ${F.unpriced}` : ""}</span>
        ))}
      </div>
      {view.price_error && <div className="small warn-text">{F.noPrice}: {view.price_error}</div>}
      <div className="label">{F.orders}</div>
      {view.orders.length === 0 ? <p className="small muted">{F.none}</p> : (
        <div className="table-wrap"><table className="calls">
          <tbody>{view.orders.slice(0, 20).map((o) => (
            <tr key={o.id}>
              <td>{new Date(o.created * 1000).toLocaleString(lang)}</td><td>{o.side}</td><td>{num(o.amount, 8)} {o.symbol}</td>
              <td>{o.fill_price ? num(o.fill_price, 8) : o.limit_price ? `≤≥ ${num(o.limit_price, 8)}` : ""}</td>
              <td>{F.status[o.status] ?? o.status}{o.note ? ` · ${o.note}` : ""}</td>
              <td>{o.status === "open" && <button className="link-btn small" onClick={() => cancel(o.id)}>{F.cancel}</button>}</td>
            </tr>))}</tbody>
        </table></div>
      )}
      <div className="row end">
        <label className="field inline"><span>{F.cash}</span><input type="number" min="1" value={cash} onChange={(e) => setCash(e.target.value)} /></label>
        <label className="field inline"><span>{F.quote}</span><input value={quote} maxLength={15} onChange={(e) => setQuote(e.target.value.toUpperCase())} /></label>
        <button className="btn small" onClick={reset} title={F.resetAsk}>{F.reset}</button>
      </div>
      {err && <div className="bad small">{err}</div>}
    </div>
  );
}

function Live({ info, reload }: { info: FinanceInfo; reload: () => void }) {
  const [cfg, setCfg] = useState<LiveSettings>(info.settings.live);
  const [symbols, setSymbols] = useState(info.settings.live.symbols.join(", "));
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const status: LiveStatus = info.live;
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setErr(""); setMsg("");
    try { await fn(); if (done) setMsg(done); } catch (e) { setErr(String((e as Error).message)); }
    reload();
  };
  const save = (next: LiveSettings) => run(async () => {
    await api.put<Settings>("/api/settings", { finance: { live: next } });
    setCfg(next);
  }, F.saved);
  const draft = { ...cfg, symbols: symbols.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean) };
  return (
    <div className="card live-settings">
      <div className="card-head"><b>{F.live}</b>
        {!cfg.sandbox && cfg.enabled && <span className="badge warn">{F.realFunds}</span>}
      </div>
      <p className="small muted">{F.liveIntro} {F.localOnly}</p>
      <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setCfg({ ...draft, enabled: e.target.checked })} />{F.enabled}</label>
      <div className="row">
        <label className="field inline"><span>{F.exchange}</span>
          <select aria-label={F.exchange} value={draft.exchange} onChange={(e) => setCfg({ ...draft, exchange: e.target.value })}>
            <option value="">{F.choose}</option>
            {info.exchanges.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <label className="field inline"><span>{F.maxOrder}</span><input type="number" min="1" value={draft.max_order} onChange={(e) => setCfg({ ...draft, max_order: Number(e.target.value) })} /></label>
        <label className="field inline"><span>{F.maxDay}</span><input type="number" min="1" value={draft.max_day} onChange={(e) => setCfg({ ...draft, max_day: Number(e.target.value) })} /></label>
      </div>
      <label className="check"><input type="checkbox" checked={draft.sandbox} onChange={(e) => setCfg({ ...draft, sandbox: e.target.checked })} />{F.sandbox}
        <span className="hint small">{F.testnets}: {status.testnets.join(", ")}</span></label>
      <label className="check warn"><input type="checkbox" checked={draft.no_withdrawal} onChange={(e) => setCfg({ ...draft, no_withdrawal: e.target.checked })} /><span className="grow">{F.noWithdrawal}</span></label>
      <label className="field"><span>{F.symbols}</span><input value={symbols} placeholder="BTC/USDT, ETH/USDT" onChange={(e) => setSymbols(e.target.value)} /></label>
      <div className="row"><button className="btn primary small" onClick={() => save(draft)}>{F.save}</button></div>

      {draft.exchange && (
        <div className="row end">
          <span className={`badge ${status.has_key && status.exchange === draft.exchange ? "ok" : ""}`}>{status.has_key && status.exchange === draft.exchange ? F.keySaved : F.noKey}</span>
          <label className="field inline"><span>{F.key}</span><input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} /></label>
          <label className="field inline"><span>{F.secret}</span><input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} /></label>
          <button className="btn small" disabled={!key || !secret} onClick={() => run(async () => {
            await api.put("/api/finance/live/key", { exchange: draft.exchange, api_key: key, secret }); setKey(""); setSecret("");
          }, F.keySaved)}>{F.saveKey}</button>
          {status.has_key && status.exchange === draft.exchange && (<>
            <button className="btn small" onClick={() => run(async () => {
              const r = await api.post<{ withdrawals: boolean | null; note: string }>("/api/finance/live/check");
              setMsg(`${F.checkOk}${r.withdrawals === true ? `. ${F.withdrawYes}` : r.withdrawals === false ? `. ${F.withdrawNo}` : r.note ? `. ${r.note}` : ""}`);
            })}>{F.check}</button>
            <button className="btn small danger" onClick={() => run(() => api.del(`/api/finance/live/key/${draft.exchange}`))}>{F.removeKey}</button>
          </>)}
        </div>
      )}
      {status.problems.length > 0
        ? <div className="small warn-text">{F.problems}<ul>{status.problems.map((p, i) => <li key={p}>{F.problem[status.problem_codes[i]] ?? p}</li>)}</ul></div>
        : <div className="small ok-text">✓ {F.ready} · {F.spent}: {num(status.spent_today)}</div>}
      {status.withdrawals === "yes" && <div className="bad small">{F.withdrawYes}</div>}
      {info.live_orders.length > 0 && (
        <div className="table-wrap"><table className="calls" aria-label={F.live}>
          <tbody>{info.live_orders.map((o) => (
            <tr key={o.id}><td>{new Date(o.created * 1000).toLocaleString(lang)}</td><td>{o.side}</td><td>{num(o.amount, 8)} {o.symbol}</td>
              <td>{o.exchange}{o.sandbox ? " (test)" : ""}</td><td>{num(o.notional)}</td><td>{F.status[o.status] ?? o.status}</td></tr>))}</tbody>
        </table></div>
      )}
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="bad small" role="alert">{err}</div>}
    </div>
  );
}

/** Settings › Finance: the exchange for prices, the paper account and the (off by default) real orders. */
export function Finance() {
  const [info, setInfo] = useState<FinanceInfo | null>(null);
  const [err, setErr] = useState("");
  const load = () => api.get<FinanceInfo>("/api/finance").then(setInfo).catch((e) => setErr(String(e.message)));
  useEffect(() => { load(); }, []);
  if (!info) return err ? <div className="bad small">{err}</div> : null;
  const setExchange = async (exchange: string) => {
    await api.put("/api/settings", { finance: { exchange } });
    load();
  };
  return (
    <div className="form">
      <p className="small muted">{F.intro}</p>
      <label className="field inline"><span>{F.prices}</span>
        <select aria-label={F.prices} value={info.settings.exchange} onChange={(e) => setExchange(e.target.value)}>
          {info.exchanges.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      </label>
      <Paper />
      <Live info={info} reload={load} />
    </div>
  );
}
