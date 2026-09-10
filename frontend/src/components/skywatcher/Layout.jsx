import { NavLink, Outlet, useLocation } from "react-router-dom";
import Sidebar, { NAV } from "./Sidebar";
import TopStatusStrip from "./TopStatusStrip";
import styles from "../../zip-design/AppShell.module.css";
import { useSkywatcher } from "@/lib/SkywatcherData";

export default function Layout() {
  const { pathname } = useLocation();
  const { loadErrors, loading, reload } = useSkywatcher();
  const failedCollections = Object.keys(loadErrors);
  const current = NAV.find(item => item.to === pathname);
  return <div className={`zip-surface ${styles.app}`}>
    <div className={styles.topStrip}><TopStatusStrip /></div>
    <div className={styles.desktopRail}><Sidebar /></div>
    <div className={styles.workspace}>
      <header className={styles.desktopHeader}><div><span className={styles.eyebrow}>AIRSPACE INTELLIGENCE</span><h1>{current?.label || 'Skywatcher PR'}</h1></div></header>
      <header className={styles.mobileHeader}><span aria-hidden="true">✈</span><div className={styles.mobileTitle}><span>Skywatcher PR</span><strong>{current?.label || 'Airspace intelligence'}</strong></div></header>
      <details className="zip-mobile-menu"><summary>All workflows</summary><Sidebar /></details>
      <main className={styles.main}>
        {failedCollections.length > 0 && <section role="alert" className="mb-4 rounded-lg border border-destructive p-3">
          <p className="font-semibold">Data is incomplete</p>
          <p>Unavailable collections: {failedCollections.join(", ")}. Previous data may be stale; empty counts do not confirm zero records.</p>
          <button type="button" onClick={reload} disabled={loading} className="mt-2 rounded border px-3 py-1">{loading ? "Retrying…" : "Retry data"}</button>
        </section>}
        <Outlet />
      </main>
      <nav className={styles.mobileTabs} aria-label="Mobile navigation">{NAV.filter(item => ['/', '/observations', '/fr24', '/review', '/export'].includes(item.to)).map(({to, label, icon: Icon}) => <NavLink key={to} to={to} end={to === '/'} className={({isActive}) => `${styles.mobileTab} ${isActive ? styles.mobileTabActive : ''}`}><Icon size={20} aria-hidden="true"/><span>{label}</span></NavLink>)}</nav>
    </div>
  </div>;
}
