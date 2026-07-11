/* FR24 in-page batch download driver  (low-credit harvest path)
 * ---------------------------------------------------------------
 * Keeps the model OUT of the per-flight loop. Inject this whole file once via
 * the Chrome MCP javascript_tool while a https://www.flightradar24.com/data/aircraft/<tail>
 * page is loaded and you are signed in as Gold, then call it ONCE per tail:
 *
 *     await fr24Batch(["3b4024f2","3b4128b0", ...], { paceMs: 1500 });
 *
 * It (1) clicks "Load earlier flights" until every requested flight row is in
 * the DOM, then (2) clicks each flight's CSV then KML export button with a
 * short pace between clicks. FR24 meters the click (check-quota); the files
 * land in ~/Downloads as <flightid>.csv / <flightid>.kml.
 *
 * HARD RULES (this is why the 2026-06-11 run failed):
 *   - Do NOT navigate the tab until `fr24_harvest.py commit-batch` has run.
 *     Navigation aborts in-flight downloads but quota is already spent.
 *   - One tail's page at a time. Finish + commit-batch before changing pages.
 *   - Returns a per-flight click log; missing rows mean the date wasn't loaded.
 *
 * Selectors (confirmed): export buttons are
 *   button[data-filetype="csv"|"kml"][data-flight="<id>"]
 * and the pager button is  #btn-load-earlier-flights .
 */
window.fr24Batch = async function (flightIds, opts = {}) {
  const paceMs    = opts.paceMs    ?? 1500;   // gap between individual clicks
  const loadWaitMs= opts.loadWaitMs?? 2800;   // wait after each "load earlier"
  const maxLoads  = opts.maxLoads  ?? 80;     // safety cap on pager clicks
  const noKml     = !!opts.noKml;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const want = new Set(flightIds.map((s) => String(s).toLowerCase()));

  const presentSet = () => {
    const have = new Set();
    document.querySelectorAll('button[data-filetype="csv"][data-flight]').forEach((b) => {
      const f = (b.dataset.flight || "").toLowerCase();
      if (want.has(f)) have.add(f);
    });
    return have;
  };

  // 1) page back until every requested flight row exists (enumeration: no quota)
  let loadsClicked = 0;
  while (presentSet().size < want.size) {
    const btn = document.querySelector("#btn-load-earlier-flights");
    if (!btn || loadsClicked >= maxLoads) break;
    btn.scrollIntoView();
    btn.click();
    loadsClicked++;
    await sleep(loadWaitMs);
  }

  // 2) click CSV then KML for each requested flight (THIS spends quota)
  const log = [];
  for (const raw of flightIds) {
    const fid = String(raw).toLowerCase();
    const csv = document.querySelector('button[data-filetype="csv"][data-flight="' + fid + '"]');
    if (!csv) {
      log.push({ fid, csv: false, kml: false, note: "row/buttons not loaded (date out of range?)" });
      continue;
    }
    csv.click();
    await sleep(paceMs);
    let kmlClicked = false;
    if (!noKml) {
      const kml = document.querySelector('button[data-filetype="kml"][data-flight="' + fid + '"]');
      if (kml) { kml.click(); kmlClicked = true; await sleep(paceMs); }
    }
    log.push({ fid, csv: true, kml: kmlClicked,
               note: noKml ? "csv only (no-kml)" : (kmlClicked ? "csv+kml clicked" : "csv ok, KML button missing") });
  }

  const missing = flightIds.filter((f) => !presentSet().has(String(f).toLowerCase()));
  return { requested: flightIds.length, loadsClicked, clicked: log.filter(l => l.csv).length, missing, log };
};
console.log("fr24Batch ready — call: await fr24Batch([...ids], {paceMs:1500})");
