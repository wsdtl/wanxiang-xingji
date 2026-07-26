import {
  buildActorVisualMap,
  renderCompactTimeline,
  renderDetailedTimeline,
  renderDetailedTimelineEntries,
  renderRawDataAccess,
} from "./timeline.js?v=18";
import {
  activateMotion,
  animateRegion,
  controlButton,
  formatTime,
  node,
  rawBlock,
  renderGauge,
  renderParticipantRecord,
  renderStatusGroup,
  replaceRegion,
  safeToken,
} from "./ui.js?v=18";

const root = document.querySelector("#reportRoot");

const state = {
  report: null,
  segmentIndex: 0,
  mode: "",
  filter: "",
  snapshot: "",
  participantExpanded: !window.matchMedia("(max-width: 640px)").matches,
};

root.addEventListener("click", handleControlClick);
root.addEventListener("change", handleControlChange);

main().catch((error) => {
  renderError(error instanceof Error ? error.message : String(error));
});

async function main() {
  const report = await loadReport();
  if (report.schema !== "game.battle_report.presentation" || report.version !== 2) {
    renderUnsupportedReport(report);
    return;
  }
  state.report = report;
  state.mode = report.ui.modes[0].id;
  state.filter = report.ui.filters[0].id;
  state.snapshot = report.ui.snapshots[report.ui.snapshots.length - 1].id;
  document.title = `${report.game_name || "万象行纪"} · ${report.summary.title}`;
  renderReport();
}

async function loadReport() {
  const embedded = document.querySelector("#battleReportPreviewData");
  if (embedded) {
    return JSON.parse(embedded.textContent || "null");
  }
  const shareId = reportShareId();
  if (!shareId) {
    throw new Error("分享地址无效。");
  }
  const path = window.location.pathname.replace(/\/$/, "");
  const response = await fetch(`${path}/data`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || "内容读取失败。");
  }
  return response.json();
}

function reportShareId() {
  const match = window.location.pathname.match(/^\/battle\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : "";
}

function handleControlClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !root.contains(button) || !state.report) {
    return;
  }
  const action = button.dataset.action;
  const value = button.dataset.value;
  if (action === "mode" && optionExists(state.report.ui.modes, value)) {
    if (state.mode !== value) {
      state.mode = value;
      updateModeView();
    }
    return;
  }
  if (action === "segment") {
    selectSegment(Number(value));
    return;
  }
  if (action === "segment-step") {
    selectSegment(state.segmentIndex + Number(value));
    return;
  }
  if (action === "snapshot" && optionExists(state.report.ui.snapshots, value)) {
    if (state.snapshot !== value) {
      state.snapshot = value;
      updateSnapshotView();
    }
    return;
  }
  if (action === "participant-disclosure") {
    state.participantExpanded = !state.participantExpanded;
    updateParticipantDisclosure();
    return;
  }
  if (action === "filter" && optionExists(state.report.ui.filters, value)) {
    if (state.filter !== value) {
      state.filter = value;
      updateFilterView();
    }
  }
}

function handleControlChange(event) {
  const select = event.target.closest('select[data-action="segment-select"]');
  if (!select || !root.contains(select) || !state.report) {
    return;
  }
  selectSegment(Number(select.value));
}

function selectSegment(index) {
  const segments = state.report.detail.segments;
  if (!Number.isInteger(index) || !segments[index] || state.segmentIndex === index) {
    return;
  }
  state.segmentIndex = index;
  state.filter = state.report.ui.filters[0].id;
  updateSegmentView();
}

function updateModeView() {
  document.body.dataset.mode = state.mode;
  root.querySelectorAll('[data-action="mode"]').forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.mode));
  });
  const panel = root.querySelector(`.mode-panel[data-mode="${CSS.escape(state.mode)}"]`);
  animateRegion(panel);
}

function updateSegmentView() {
  const segment = currentSegment();
  const ui = state.report.ui;
  replaceRegion(root, ".segment-tabs", renderSegmentNavigation(state.report.detail.segments));
  replaceRegion(root, ".segment-overview", renderMatchup(segment));
  replaceRegion(root, ".report-body", renderReportBody(segment));
  replaceRegion(root, ".raw-report-details", renderRawDataAccess(segment, ui));
  animateRegion(root.querySelector(".segment-overview"));
  animateRegion(root.querySelector(".report-body"));
  requestAnimationFrame(() => activateMotion(root));
}

function updateSnapshotView() {
  const segment = currentSegment();
  const participants = snapshotParticipants(segment);
  const actorVisuals = buildActorVisualMap(segment.combatants);
  const disclosure = root.querySelector(".participant-disclosure");
  if (!disclosure) {
    return;
  }
  const option = state.report.ui.snapshots.find((item) => item.id === state.snapshot);
  const label = disclosure.querySelector(".participant-disclosure-title span");
  if (label) {
    label.textContent = option.label;
  }
  const snapshotSwitch = disclosure.querySelector(".snapshot-switch");
  if (snapshotSwitch) {
    snapshotSwitch.dataset.snapshot = state.snapshot;
    snapshotSwitch.querySelectorAll('[data-action="snapshot"]').forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.value === state.snapshot));
    });
  }
  replaceRegion(
    root,
    ".participant-stack",
    node(
      "div",
      "participant-stack region-update",
      participants.map((participant) => renderParticipantSummary(participant, actorVisuals)),
    ),
  );
  requestAnimationFrame(() => activateMotion(root));
}

function updateParticipantDisclosure() {
  const disclosure = root.querySelector(".participant-disclosure");
  const button = disclosure?.querySelector(".participant-disclosure-title");
  const content = disclosure?.querySelector(".participant-disclosure-content");
  if (!disclosure || !button || !content) {
    return;
  }
  disclosure.dataset.expanded = String(state.participantExpanded);
  button.setAttribute("aria-expanded", String(state.participantExpanded));
  content.setAttribute("aria-hidden", String(!state.participantExpanded));
  content.toggleAttribute("inert", !state.participantExpanded);
  if (state.participantExpanded) {
    animateRegion(content);
  }
}

function updateFilterView() {
  root.querySelectorAll('[data-action="filter"]').forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.filter));
  });
  replaceRegion(
    root,
    ".detailed-timeline",
    renderDetailedTimelineEntries(currentSegment(), state.filter, state.report.ui),
  );
}

function currentSegment() {
  return state.report.detail.segments[state.segmentIndex];
}

function renderReport() {
  const report = state.report;
  const text = report.ui.text;
  document.body.dataset.mode = state.mode;
  root.replaceChildren();
  root.className = "report-shell report-ready";

  if (!report.detail.available) {
    root.append(renderSummaryHeader(report));
    root.append(
      node("section", "notice", [
        node("p", "section-kicker", text.archive_kicker),
        node("h2", "", text.archive_title),
        node("p", "", report.detail.retention_notice),
      ]),
    );
    return;
  }

  const segments = report.detail.segments;
  state.segmentIndex = Math.min(state.segmentIndex, Math.max(segments.length - 1, 0));
  const segment = segments[state.segmentIndex];
  root.append(renderSummaryHeader(report));
  if (segments.length > 1) {
    root.append(renderSegmentNavigation(segments));
  }
  root.append(renderMatchup(segment));
  root.append(renderViewToolbar());
  root.append(renderReportBody(segment));
  root.append(renderRawDataAccess(segment, report.ui));
  requestAnimationFrame(() => activateMotion(root));
}

function renderSummaryHeader(report) {
  const text = report.ui.text;
  const header = node("header", "report-header");
  header.append(
    node("div", "brand-line", [
      node("span", "brand-name", report.game_name || "万象行纪"),
      node("span", "brand-divider", text.brand_suffix),
    ]),
  );
  header.append(
    node("div", "title-row", [
      node("div", "title-copy", [
        node("h1", "", report.summary.title),
        node("p", "report-time", `${formatTime(report.started_at)} 至 ${formatTime(report.finished_at)}`),
      ]),
      node("div", `result-stamp ${safeToken(report.summary.tone)}`, [
        node("span", "", text.settlement_label),
        node("strong", "", report.summary.outcome),
      ]),
    ]),
  );
  const lines = report.summary.lines || [];
  if (!lines.length) {
    return header;
  }
  header.append(node("ul", "summary-lines", lines.slice(0, 2).map((line) => node("li", "", line))));
  if (lines.length > 2) {
    const more = node("details", "summary-lines-more");
    more.append(node("summary", "", text.more_summary));
    more.append(node("ul", "summary-more-list", lines.slice(2).map((line) => node("li", "", line))));
    header.append(more);
  }
  return header;
}

function renderMatchup(segment) {
  const participants = segment.final_participants.length
    ? segment.final_participants
    : segment.initial_participants;
  const teams = groupByTeam(participants);
  if (!teams.length) {
    return node("div", "matchup segment-overview empty", state.report.ui.text.empty_participants);
  }
  const first = renderTeamSummary(teams[0]);
  if (teams.length === 1) {
    return node("section", "matchup segment-overview single", first);
  }
  const last = renderTeamSummary(teams[teams.length - 1], true);
  const middleTeams = Math.max(0, teams.length - 2);
  return node("section", "matchup segment-overview", [
    first,
    node("div", "versus", [
      node("strong", "", segment.outcome),
      segment.duration_label ? node("span", "", segment.duration_label) : null,
      middleTeams
        ? node(
            "small",
            "",
            state.report.ui.text.additional_team_template.replace("{count}", String(middleTeams)),
          )
        : null,
    ]),
    last,
  ]);
}

function renderTeamSummary(team, reverse = false) {
  const names = team.participants.map((item) => item.label).join("、");
  return node("div", `combat-side${reverse ? " enemy" : ""}`, [
    node("div", "side-name", [
      node("span", "", team.label),
      node("strong", "", names),
    ]),
  ]);
}

function renderSegmentNavigation(segments) {
  const text = state.report.ui.text;
  const many = segments.length > 6;
  const select = node(
    "select",
    "segment-select",
    segments.map((segment, index) => {
      const option = node("option", "", `${String(index + 1).padStart(2, "0")}/${segments.length} · ${segment.title}`);
      option.value = String(index);
      option.selected = index === state.segmentIndex;
      return option;
    }),
  );
  select.dataset.action = "segment-select";
  select.setAttribute("aria-label", text.segment_select_label);
  return node("nav", `segment-tabs${many ? " many-segments" : ""}`, [
    node("span", "segment-label", [
      document.createTextNode(text.segment_label),
      node("small", "segment-count", `${state.segmentIndex + 1} / ${segments.length}`),
    ]),
    node("div", "segment-navigation", [
      segmentStepButton(text.previous_segment_label, -1, state.segmentIndex === 0),
      node("label", "segment-picker", [select]),
      node(
        "div",
        "segment-scroll",
        segments.map((segment, index) =>
          controlButton(segment.title, "segment", String(index), index === state.segmentIndex),
        ),
      ),
      segmentStepButton(text.next_segment_label, 1, state.segmentIndex === segments.length - 1),
    ]),
  ]);
}

function segmentStepButton(label, direction, disabled) {
  const button = node("button", "segment-step", direction < 0 ? "‹" : "›");
  button.type = "button";
  button.dataset.action = "segment-step";
  button.dataset.value = String(direction);
  button.disabled = disabled;
  button.setAttribute("aria-label", label);
  button.title = label;
  return button;
}

function renderViewToolbar() {
  return node("section", "view-toolbar", [
    node(
      "div",
      "mode-switch",
      state.report.ui.modes.map((option) =>
        controlButton(option.label, "mode", option.id, state.mode === option.id),
      ),
    ),
  ]);
}

function renderReportBody(segment) {
  return node("section", "report-body view-panel", [
    renderSummaryPanel(segment),
    node("section", "timeline-panel", [
      renderCompactTimeline(segment, state.report.ui),
      renderDetailedTimeline(segment, state.filter, state.report.ui),
    ]),
  ]);
}

function renderSummaryPanel(segment) {
  const participants = snapshotParticipants(segment);
  const actorVisuals = buildActorVisualMap(segment.combatants);
  const selected = state.report.ui.snapshots.find((item) => item.id === state.snapshot);
  const snapshotSwitch = node(
    "div",
    "snapshot-switch",
    state.report.ui.snapshots.map((option) =>
      controlButton(option.label, "snapshot", option.id, state.snapshot === option.id),
    ),
  );
  snapshotSwitch.dataset.snapshot = state.snapshot;
  const disclosureButton = node("button", "participant-disclosure-title", [
    node("strong", "", state.report.ui.text.participant_panel_title),
    node("span", "", selected.label),
  ]);
  disclosureButton.type = "button";
  disclosureButton.dataset.action = "participant-disclosure";
  disclosureButton.setAttribute("aria-controls", "participantDetails");
  disclosureButton.setAttribute("aria-expanded", String(state.participantExpanded));
  const disclosureContent = node("div", "participant-disclosure-content", [
    node("div", "participant-disclosure-inner", [
      node("div", "panel-heading", [snapshotSwitch]),
      node(
        "div",
        "participant-stack",
        participants.map((participant) => renderParticipantSummary(participant, actorVisuals)),
      ),
    ]),
  ]);
  disclosureContent.id = "participantDetails";
  disclosureContent.setAttribute("aria-hidden", String(!state.participantExpanded));
  disclosureContent.toggleAttribute("inert", !state.participantExpanded);
  const disclosure = node("section", "participant-disclosure", [disclosureButton, disclosureContent]);
  disclosure.dataset.expanded = String(state.participantExpanded);
  return node("aside", "summary-panel", disclosure);
}

function renderParticipantSummary(participant, actorVisuals) {
  const actor = actorVisuals.get(participant.key);
  const actorColor = actor?.color || "system";
  const actorNumber = actor ? String(actor.number).padStart(2, "0") : "--";
  const badge = node("span", `participant-index actor-${actorColor}`, actorNumber);
  badge.dataset.actorKey = participant.key;
  badge.dataset.actorColor = actorColor;
  return node("article", "participant-summary", [
    node("div", "participant-heading", [
      badge,
      node("div", "", [node("strong", "", participant.label)]),
    ]),
    ...(participant.gauges || []).map((gauge) => renderGauge(gauge)),
    renderStatusGroup(participant.status_group),
    renderParticipantRecord(participant),
  ]);
}

function snapshotParticipants(segment) {
  const firstId = state.report.ui.snapshots[0].id;
  if (state.snapshot === firstId) {
    return segment.initial_participants;
  }
  return segment.final_participants.length
    ? segment.final_participants
    : segment.initial_participants;
}

function groupByTeam(participants) {
  const teams = new Map();
  participants.forEach((participant) => {
    const key = participant.team_id;
    if (!teams.has(key)) {
      teams.set(key, { id: key, label: participant.team_label, participants: [] });
    }
    teams.get(key).participants.push(participant);
  });
  return [...teams.values()];
}

function optionExists(options, value) {
  return options.some((item) => item.id === value);
}

function renderUnsupportedReport(report) {
  root.replaceChildren(
    node("section", "error-state", [
      node("h1", "", "内容协议暂不支持"),
      node("p", "", `收到协议版本 ${String(report?.version ?? "-")}。`),
      rawBlock(report),
    ]),
  );
}

function renderError(message) {
  root.replaceChildren(
    node("section", "error-state", [
      node("h1", "", "内容暂时无法打开"),
      node("p", "", message),
    ]),
  );
}
