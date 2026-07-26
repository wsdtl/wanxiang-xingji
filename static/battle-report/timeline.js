import {
  node,
  rawBlock,
  renderFacts,
  renderSnapshotParticipant,
  safeToken,
} from "./ui.js?v=18";

const ACTOR_PALETTE_SIZE = 16;

export function renderCompactTimeline(segment, ui) {
  const mode = ui.modes[0];
  const actorVisuals = buildActorVisualMap(segment.combatants);
  const section = node("section", "mode-panel compact-panel");
  section.dataset.mode = mode.id;
  section.append(renderTimelineHeading(mode.label));
  const timeline = node("div", "timeline compact-timeline");
  if (!segment.timeline.length) {
    timeline.append(node("p", "empty-state", ui.text.empty_timeline));
  }
  let previousRound = "";
  segment.timeline.forEach((entry) => {
    if (entry.round_label && entry.round_label !== previousRound) {
      timeline.append(node("div", "round-heading", entry.round_label));
      previousRound = entry.round_label;
    }
    timeline.append(renderCompactEntry(entry, ui, actorVisuals));
  });
  section.append(timeline);
  return section;
}

export function renderDetailedTimeline(segment, filter, ui) {
  const mode = ui.modes[1] || ui.modes[0];
  const events = flattenEvents(segment.timeline);
  const section = node("section", "mode-panel detail-panel");
  section.dataset.mode = mode.id;
  section.append(renderTimelineHeading(mode.label));
  section.append(
    node(
      "div",
      "event-filters",
      ui.filters.map((option, index) => {
        const count = events.filter((event) => matchesFilter(event, option.id, ui)).length;
        const button = node("button", "control-button", `${option.label} ${count}`);
        button.type = "button";
        button.dataset.action = "filter";
        button.dataset.value = option.id;
        button.setAttribute("aria-pressed", String(filter === option.id));
        button.dataset.filterIndex = String(index);
        return button;
      }),
    ),
  );
  section.append(renderDetailedTimelineEntries(segment, filter, ui));
  return section;
}

export function renderDetailedTimelineEntries(segment, filter, ui) {
  const actorVisuals = buildActorVisualMap(segment.combatants);
  const timeline = node("div", "timeline detailed-timeline region-update");
  const entries = segment.timeline.filter(
    (entry) => entry.events.some((event) => matchesFilter(event, filter, ui)),
  );
  if (!entries.length) {
    timeline.append(node("p", "empty-state", ui.text.empty_filter));
  }
  entries.forEach((entry) => timeline.append(renderDetailedEntry(entry, filter, ui, actorVisuals)));
  return timeline;
}

export function buildActorVisualMap(combatants = []) {
  const actors = new Map();
  combatants.forEach((combatant, index) => {
    actors.set(combatant.key, {
      color: String(index % ACTOR_PALETTE_SIZE),
      number: index + 1,
    });
  });
  return actors;
}

export function renderRawDataAccess(segment, ui) {
  const details = node("details", "raw-report-details");
  details.append(node("summary", "", ui.text.raw_data_label));
  details.addEventListener("toggle", () => {
    if (!details.open || details.dataset.loaded === "true") {
      return;
    }
    details.dataset.loaded = "true";
    details.append(rawBlock(segment));
  });
  return details;
}

function renderCompactEntry(entry, ui, actorVisuals) {
  const primaryEvents = entry.events.filter((event) => event.compact_visible);
  const secondaryEvents = entry.events.filter((event) => !event.compact_visible);
  const article = node("article", `action-card tone-${safeToken(entry.tone)}`);
  article.append(node("div", "action-head", [node("div", "action-title", entry.title)]));
  if (primaryEvents.length) {
    const events = node("ol", "event-list compact-event-list");
    primaryEvents.forEach((event) => events.append(renderEvent(event, false, ui, actorVisuals)));
    article.append(events);
  }
  if (secondaryEvents.length) {
    article.append(renderEventGroup(ui.text.process_group_label, secondaryEvents, ui, actorVisuals));
  }
  article.append(renderComparison(entry.comparison, ui));
  return article;
}

function renderDetailedEntry(entry, filter, ui, actorVisuals) {
  const article = node("article", `action-card detailed-action tone-${safeToken(entry.tone)}`);
  article.append(
    node("div", "action-head", [
      node("div", "action-title", entry.title),
      node("div", "action-sequence", entry.sequence_label),
    ]),
  );
  if (entry.facts.length) {
    article.append(renderFacts(entry.facts, "fact-row"));
  }
  const eventList = node("ol", "event-list");
  entry.events
    .filter((event) => matchesFilter(event, filter, ui))
    .forEach((event) => eventList.append(renderEvent(event, true, ui, actorVisuals)));
  article.append(eventList);
  article.append(renderComparison(entry.comparison, ui));
  return article;
}

function renderEvent(event, includeFacts, ui, actorVisuals) {
  const item = node("li", "event");
  item.dataset.tone = event.tone || "neutral";
  item.dataset.category = event.category || "";
  item.append(
    node("div", "event-heading", [
      renderEventMarker(event, actorVisuals),
      includeFacts ? node("span", "event-label", event.label) : null,
      node("span", "event-text", event.text),
    ]),
  );
  if (includeFacts && event.facts.length) {
    item.append(
      node(
        "div",
        "event-facts",
        event.facts.map((fact) => `${fact.label}: ${fact.display}`).join(" · "),
      ),
    );
  }
  if (includeFacts) {
    const raw = node("details", "raw-details");
    raw.append(node("summary", "", ui.text.event_facts_label));
    raw.append(rawBlock(event.raw));
    item.append(raw);
  }
  return item;
}

function renderEventMarker(event, actorVisuals) {
  const sourceKey = event.source?.key || "";
  const actorColor = event.category === "system"
    ? "system"
    : actorVisuals.get(sourceKey)?.color || "system";
  const marker = node(
    "span",
    `event-marker actor-${actorColor}`,
    "",
  );
  marker.dataset.actorKey = actorColor === "system" ? "system" : sourceKey;
  marker.dataset.actorColor = actorColor;
  marker.dataset.eventCategory = event.category || "";
  marker.title = actorColor === "system"
    ? event.label
    : `${event.source?.label || sourceKey} · ${event.label}`;
  marker.setAttribute("aria-hidden", "true");
  return marker;
}

function renderEventGroup(title, events, ui, actorVisuals) {
  const details = node("details", "event-group");
  details.append(node("summary", "", `${title} · ${events.length}`));
  const list = node("ol", "event-list");
  events.forEach((event) => list.append(renderEvent(event, false, ui, actorVisuals)));
  details.append(list);
  return details;
}

function renderComparison(comparison, ui) {
  const details = node("details", "frame-comparison");
  details.append(node("summary", "", comparison.title));
  details.append(renderChanges(comparison));
  const grid = node("div", "frame-grid");
  if (comparison.before) {
    grid.append(renderFrame(comparison.before));
  }
  if (comparison.after) {
    grid.append(renderFrame(comparison.after));
  }
  details.append(grid);
  return details;
}

function renderChanges(comparison) {
  if (!comparison.changes.length) {
    return node("p", "state-diff muted", comparison.empty_text);
  }
  return node(
    "ul",
    "state-diff",
    comparison.changes.map((change) => {
      const item = node("li", `tone-${safeToken(change.tone)}`, change.text);
      return item;
    }),
  );
}

function renderFrame(frame) {
  const article = node("article", "snapshot");
  article.append(
    node("div", "snapshot-heading", [
      node("strong", "", frame.title),
      node("span", "", frame.round_turn_label),
    ]),
  );
  article.append(renderFacts(frame.facts, "snapshot-facts"));
  article.append(
    node(
      "div",
      "snapshot-participants",
      frame.participants.map((participant) => renderSnapshotParticipant(participant)),
    ),
  );
  return article;
}

function renderTimelineHeading(title) {
  return node("div", "timeline-heading", [node("h2", "", title)]);
}

function matchesFilter(event, filter, ui) {
  return filter === ui.filters[0].id || event.category === filter;
}

function flattenEvents(timeline) {
  return timeline.flatMap((entry) => entry.events || []);
}
