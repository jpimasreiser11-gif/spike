import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { lang } from "../i18n";
import type { LiveOrder } from "../types";
export const STATUS: Record<string, string> = lang === "es"
  ? { proposed: "esperando tu confirmación", sending: "enviando", placed: "enviada", failed: "fallida", cancelled: "cancelada", expired: "caducada", open: "abierta", filled: "ejecutada" }
  : { proposed: "waiting for your confirmation", sending: "sending", placed: "sent", failed: "failed", cancelled: "cancelled", expired: "expired", open: "open", filled: "filled" };

export const C = lang === "es"
  ? { title: "Orden real propuesta", test: "red de pruebas", real: "DINERO REAL", about: "aprox.", confirm: "Confirmar", sure: "¿Enviar esta orden a", yes: "Sí, enviar", no: "No",
      cancel: "Cancelar", expires: "caduca en", min: "min", limit: "límite", market: "a mercado", buy: "Comprar", sell: "Vender" }
  : { title: "Proposed real order", test: "test network", real: "REAL FUNDS", about: "about", confirm: "Confirm", sure: "Send this order to", yes: "Yes, send it", no: "No",
      cancel: "Cancel", expires: "expires in", min: "min", limit: "limit", market: "at market", buy: "Buy", sell: "Sell" };

const TTL_S = 600;
export const num = (x: number, d = 2) => x.toLocaleString(lang, { maximumFractionDigits: d });

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
        <span className={`badge status-${order.status}`}>{STATUS[order.status] ?? order.status}</span>
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
