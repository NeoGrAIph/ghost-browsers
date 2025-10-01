import { RunnerState, RunnerStatus } from '../types/runner';
import { Session } from '../types/session';

/**
 * Describes a selectable option rendered by the session composer form.
 */
export interface SessionComposerOption {
  readonly id: string;
  readonly label: string;
}

/**
 * Describes a runner that can be targeted explicitly from the composer.
 */
export interface RunnerChoice extends SessionComposerOption {
  readonly healthy: boolean;
  readonly supportsVnc: boolean;
  readonly state: RunnerState;
  readonly availableSlots: number | null;
  readonly browsers: readonly string[];
  readonly regions: readonly string[];
  readonly proxies: readonly string[];
}

/**
 * Aggregated catalogue of options required to populate the session composer.
 */
export interface SessionComposerData {
  readonly browsers: readonly SessionComposerOption[];
  readonly regions: readonly SessionComposerOption[];
  readonly proxies: readonly SessionComposerOption[];
  readonly runners: readonly RunnerChoice[];
}

interface MutableRunnerCapabilities {
  readonly browsers: Set<string>;
  readonly regions: Set<string>;
  readonly proxies: Set<string>;
}

interface ParsedCapability {
  readonly kind: 'browser' | 'region' | 'proxy';
  readonly value: string;
  readonly label: string | null;
}

const CAPABILITY_PATTERN = /^(?<key>[a-z0-9_-]+)\s*(?:[:=])\s*(?<value>.+)$/i;

const normaliseLabel = (value: string) => value.trim().replace(/\s+/g, ' ');

const parseCapability = (raw: string): ParsedCapability | null => {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }

  const match = CAPABILITY_PATTERN.exec(trimmed);
  if (!match || !match.groups) {
    return null;
  }

  const key = match.groups.key.toLowerCase();
  const rawValue = match.groups.value.trim();
  if (!rawValue) {
    return null;
  }

  const [identifier, maybeLabel] = rawValue.split('|', 2).map((part) => part.trim());
  const value = identifier ?? rawValue;
  const label = maybeLabel ? normaliseLabel(maybeLabel) : null;

  if (key === 'browser' || key === 'region' || key === 'proxy') {
    return { kind: key, value, label };
  }

  return null;
};

const ensureCapabilityEntry = (
  map: Map<string, MutableRunnerCapabilities>,
  runnerId: string,
): MutableRunnerCapabilities => {
  const existing = map.get(runnerId);
  if (existing) {
    return existing;
  }
  const created: MutableRunnerCapabilities = {
    browsers: new Set<string>(),
    regions: new Set<string>(),
    proxies: new Set<string>(),
  };
  map.set(runnerId, created);
  return created;
};

const upsertOption = (
  map: Map<string, SessionComposerOption>,
  id: string,
  label: string | null,
) => {
  if (!map.has(id)) {
    map.set(id, { id, label: label ?? id });
  }
};

const collectFromRunnerCapabilities = (
  runners: readonly RunnerStatus[],
  capabilityMap: Map<string, MutableRunnerCapabilities>,
  browserOptions: Map<string, SessionComposerOption>,
  regionOptions: Map<string, SessionComposerOption>,
  proxyOptions: Map<string, SessionComposerOption>,
) => {
  for (const runner of runners) {
    const entry = ensureCapabilityEntry(capabilityMap, runner.id);
    for (const raw of runner.capabilities) {
      const capability = parseCapability(raw);
      if (!capability) {
        continue;
      }

      if (capability.kind === 'browser') {
        entry.browsers.add(capability.value);
        upsertOption(browserOptions, capability.value, capability.label);
      } else if (capability.kind === 'region') {
        entry.regions.add(capability.value);
        upsertOption(regionOptions, capability.value, capability.label);
      } else if (capability.kind === 'proxy') {
        entry.proxies.add(capability.value);
        upsertOption(proxyOptions, capability.value, capability.label);
      }
    }
  }
};

const collectFromSessions = (
  sessions: readonly Session[],
  capabilityMap: Map<string, MutableRunnerCapabilities>,
  browserOptions: Map<string, SessionComposerOption>,
  regionOptions: Map<string, SessionComposerOption>,
  proxyOptions: Map<string, SessionComposerOption>,
) => {
  for (const session of sessions) {
    const entry = ensureCapabilityEntry(capabilityMap, session.runnerId);
    entry.browsers.add(session.browser);
    upsertOption(browserOptions, session.browser, null);

    if (session.region) {
      entry.regions.add(session.region);
      upsertOption(regionOptions, session.region, null);
    }

    if (session.proxyId) {
      entry.proxies.add(session.proxyId);
      upsertOption(proxyOptions, session.proxyId, session.proxyLabel);
    }
  }
};

const sortOptions = (options: Iterable<SessionComposerOption>) =>
  Array.from(options).sort((a, b) => a.label.localeCompare(b.label, 'en'));

/**
 * Builds the set of composer options by combining runner capabilities and sessions.
 */
export const buildSessionComposerData = (
  runners: readonly RunnerStatus[],
  sessions: readonly Session[],
): SessionComposerData => {
  const capabilityMap = new Map<string, MutableRunnerCapabilities>();
  const browsers = new Map<string, SessionComposerOption>();
  const regions = new Map<string, SessionComposerOption>();
  const proxies = new Map<string, SessionComposerOption>();

  collectFromRunnerCapabilities(runners, capabilityMap, browsers, regions, proxies);
  collectFromSessions(sessions, capabilityMap, browsers, regions, proxies);

  const runnerChoices: RunnerChoice[] = runners.map((runner) => {
    const entry = capabilityMap.get(runner.id) ?? {
      browsers: new Set<string>(),
      regions: new Set<string>(),
      proxies: new Set<string>(),
    };

    return {
      id: runner.id,
      label: runner.id,
      healthy: runner.healthy,
      supportsVnc: runner.supportsVnc,
      state: runner.state,
      availableSlots: runner.availableSlots,
      browsers: Array.from(entry.browsers),
      regions: Array.from(entry.regions),
      proxies: Array.from(entry.proxies),
    };
  });

  return {
    browsers: sortOptions(browsers.values()),
    regions: sortOptions(regions.values()),
    proxies: sortOptions(proxies.values()),
    runners: runnerChoices,
  };
};

