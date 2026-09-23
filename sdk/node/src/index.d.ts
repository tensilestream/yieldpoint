export type YieldpointRoute = "pass" | "unverified" | "repair" | "escalate" | "block" | string;
export interface Verdict { schema_version?: number; status: YieldpointRoute; findings?: unknown[]; checked?: string[]; skipped?: string[]; prescription?: string; [key: string]: unknown }
export interface Change { path: string; before?: string; after?: string }
export interface VerificationState { diff?: string; yieldpoint_diff?: string; changes?: Change[]; yieldpoint_changes?: Change[]; verdict?: Verdict; prescription?: string; yieldpoint_history?: string[]; yieldpoint_attempts?: number; yieldpoint_loop_tripped?: boolean; [key: string]: unknown }
export interface VerifyOptions { executable?: string; executableArgs?: string[]; cwd?: string; root?: string; policy?: string; timeoutMs?: number; extract?: (state: VerificationState) => { diff?: string; changes?: Change[] } | null; verdictKey?: string; window?: number; maxRepeats?: number }
export declare class YieldpointCLIError extends Error {}
export declare class YieldpointCLIUnavailableError extends YieldpointCLIError {}
export declare class YieldpointCLITimeoutError extends YieldpointCLIError {}
export declare class YieldpointVerdictError extends YieldpointCLIError {}
export declare const PASS: "pass", UNVERIFIED: "unverified", REPAIR: "repair", ESCALATE: "escalate", BLOCK: "block";
export declare function verifyNode(options?: VerifyOptions): (state: VerificationState) => Promise<Partial<VerificationState>>;
export declare function verify(state: VerificationState, options?: VerifyOptions): Promise<Verdict>;
export declare function readChange(state: VerificationState): { diff?: string; changes?: Change[] } | null;
export declare function makeRouter(options?: { maxRepairs?: number; verdictKey?: string; onExhausted?: YieldpointRoute; onStalled?: YieldpointRoute; onUnverified?: YieldpointRoute }): (state: VerificationState) => YieldpointRoute;
export declare function routeOnVerdict(state: VerificationState): YieldpointRoute;
export declare function repairContext(state: VerificationState, verdictKey?: string): string;
export declare function verdictFrom(state: VerificationState, key?: string): Verdict;
export interface RoutingProfile { schema_version: 1; profile_id: string; coverage: Record<string, unknown>; requirements: { capabilities: string[]; [key: string]: unknown }; handoff: { max_model_switches: number; [key: string]: unknown }; [key: string]: unknown }
export interface RoutingSession { routing_session_version: 1; task_id: string; profile_id: string; switch_count: number; [key: string]: unknown }
export declare const ROUTING_PROFILE_SCHEMA_VERSION: 1;
export declare const ROUTING_SESSION_SCHEMA_VERSION: 1;
export declare function validateRoutingProfile(profile: RoutingProfile): RoutingProfile;
export declare function validateRoutingSession(session: RoutingSession): RoutingSession;
export declare function canHandoff(session: RoutingSession, profile: RoutingProfile, request?: { event?: string; candidateCapabilities?: string[] }): { allowed: boolean; reason: string };
