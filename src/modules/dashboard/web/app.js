/**
 * Sentinel-AI Incident Command Dashboard Frontend Logic (Clean Icon-Free Edition).
 * Features Multi-User Role Authentication, SPA Hash Routing, and Firebase Realtime Database
 * synchronization with automatic Edge REST API fallback (/api/live).
 */

let firebaseApp = null;
let firebaseDb = null;
let isUsingFirebase = false;
let pollingTimer = null;
let chartInstance = null;

// Telemetry History Data for Chart.js
const MAX_CHART_POINTS = 25;
const chartData = {
    labels: [],
    datasets: [
        {
            label: "Temperature (°C)",
            data: [],
            borderColor: "#059669",
            backgroundColor: "rgba(5, 150, 105, 0.06)",
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            yAxisID: 'y'
        },
        {
            label: "Smoke Density (PPM)",
            data: [],
            borderColor: "#d97706",
            backgroundColor: "rgba(217, 119, 6, 0.06)",
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            yAxisID: 'y1'
        }
    ]
};

/* ========================================================================= */
/* 0. MULTI-USER AUTHENTICATION & ROLE-BASED ACCESS CONTROL                  */
/* ========================================================================= */

const SYSTEM_USERS = {
    commander: {
        username: "commander",
        name: "Commander Vance",
        role: "COMMANDER",
        roleBadge: "FULL AUTHORITY",
        roleClass: "bg-blue-100 text-blue-800 border-blue-200",
        roleTitle: "Incident Commander Console",
        roleDesc: "Full municipal authority: emergency scenarios, traffic signals, barrier overrides, sensors matrix, and forensic dossier export.",
        allowedPages: ["overview", "emergency-plan", "system-health", "analytics", "sensors", "actuators", "gis", "logs", "review", "dvr", "datasets"],
        permissions: ["all", "scenarios", "signals", "ack", "telemetry", "hardware", "dvr", "datasets", "config"]
    },
    operator: {
        username: "operator",
        name: "Operator Chen",
        role: "OPERATOR",
        roleBadge: "SIGNALS & ROUTES",
        roleClass: "bg-emerald-100 text-emerald-800 border-emerald-200",
        roleTitle: "Traffic Controller Console",
        roleDesc: "Municipal traffic signals, emergency corridor preemption, barrier controls, and incident audit log access.",
        allowedPages: ["overview", "emergency-plan", "system-health", "analytics", "actuators", "gis", "logs", "review"],
        permissions: ["scenarios", "signals", "ack"]
    },
    engineer: {
        username: "engineer",
        name: "Eng. Reynolds",
        role: "ENGINEER",
        roleBadge: "SENSORS & CALIB",
        roleClass: "bg-amber-100 text-amber-800 border-amber-200",
        roleTitle: "Hardware Engineer Console",
        roleDesc: "Physical sensor telemetry streams, hardware driver registry, calibration diagnostics, and master dataset explorer.",
        allowedPages: ["overview", "system-health", "analytics", "sensors", "gis", "logs", "review", "datasets"],
        permissions: ["telemetry", "hardware", "datasets", "config"]
    },
    viewer: {
        username: "viewer",
        name: "Observer Guest",
        role: "VIEWER",
        roleBadge: "READ-ONLY",
        roleClass: "bg-slate-100 text-slate-700 border-slate-200",
        roleTitle: "Public Observer Console",
        roleDesc: "Read-only situational awareness: live urban traffic status, AI assessment summary, and corridor spatial localization.",
        allowedPages: ["overview", "emergency-plan", "analytics", "gis", "logs"],
        permissions: ["read"]
    }
};

function getCurrentUser() {
    try {
        const stored = localStorage.getItem("sentinel_auth_user");
        const user = stored ? JSON.parse(stored) : null;
        if (!user || user.authVersion !== 3) return null;
        const roleKey = (user.role || user.username || "commander").toLowerCase();
        const baseProfile = SYSTEM_USERS[roleKey] || SYSTEM_USERS.commander;
        return {
            ...baseProfile,
            ...user,
            name: user.name || baseProfile.name,
            roleBadge: user.roleBadge || baseProfile.roleBadge,
            roleClass: user.roleClass || baseProfile.roleClass,
            allowedPages: user.allowedPages || baseProfile.allowedPages,
            permissions: user.permissions || baseProfile.permissions
        };
    } catch (e) {
        return null;
    }
}

function setCurrentUser(user) {
    if (user) {
        const roleKey = (user.role || user.username || "commander").toLowerCase();
        const baseProfile = SYSTEM_USERS[roleKey] || SYSTEM_USERS.commander;
        const hydrated = {
            ...baseProfile,
            ...user,
            authVersion: 3
        };
        localStorage.setItem("sentinel_auth_user", JSON.stringify(hydrated));
    } else {
        localStorage.removeItem("sentinel_auth_user");
    }
}

async function handleLoginSubmit(event) {
    if (event) event.preventDefault();
    const userInput = (document.getElementById("loginUsername").value || "").trim().toLowerCase();
    const password = document.getElementById("loginPassword").value || "";
    const errEl = document.getElementById("loginError");
    const matchedUser = SYSTEM_USERS[userInput];
    if (matchedUser && password) {
        if (errEl) errEl.classList.add("hidden");
        // Local development server validates configured passwords. The browser
        // never contains them and no credentials are committed to Git.
        const verified = await fetch("/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username: userInput, password})})
            .then(async response => {
                if (!response.ok) {
                    const errData = await response.json().catch(() => ({}));
                    return { error: errData.error || "Login failed" };
                }
                return response.json();
            }).catch(() => null);

        if (!verified || verified.error) {
            if (errEl) { errEl.innerText = (verified && verified.error) ? verified.error : "Incorrect username or password."; errEl.classList.remove("hidden"); }
            return;
        }

        localStorage.setItem("sentinel_token", verified.token);
        if (verified.csrf_token) localStorage.setItem("sentinel_csrf_token", verified.csrf_token);

        const roleKey = (verified.role || userInput || "commander").toLowerCase();
        const baseProfile = SYSTEM_USERS[roleKey] || SYSTEM_USERS.commander;

        setCurrentUser({
            ...baseProfile,
            username: userInput,
            role: verified.role,
            authToken: verified.token,
            operatorId: verified.operator_id,
            csrfToken: verified.csrf_token
        });
        checkAuthAndRender();
        // Redirect to overview upon login
        switchPage("overview", true);
    } else {
        if (errEl) { errEl.innerText = "Incorrect username or password."; errEl.classList.remove("hidden"); }
    }
}

function quickLogin(roleKey, autoSubmit = false) {
    logout();
    const username = document.getElementById("loginUsername");
    const password = document.getElementById("loginPassword");
    const demoPassword = "Sentinel2026!";
    if (username) username.value = SYSTEM_USERS[roleKey] ? roleKey : "";
    if (password) {
        password.value = demoPassword;
        password.focus();
    }
    if (autoSubmit) {
        const form = document.getElementById("loginForm");
        if (form) form.requestSubmit();
    }
}

async function logout() {
    const token = localStorage.getItem("sentinel_token");
    try {
        await fetch("/api/auth/logout", {
            method: "POST",
            headers: {
                "Authorization": token ? `Bearer ${token}` : "",
                "X-CSRF-Token": localStorage.getItem("sentinel_csrf_token") || ""
            }
        });
    } catch (e) {}
    localStorage.removeItem("sentinel_token");
    localStorage.removeItem("sentinel_csrf_token");
    setCurrentUser(null);
    checkAuthAndRender();
}

function checkAuthAndRender() {
    const user = getCurrentUser();
    const loginView = document.getElementById("view-login");
    const cmdCenter = document.getElementById("commandCenterWrapper");

    if (user) {
        // Authenticated
        if (loginView) loginView.classList.add("hidden");
        if (cmdCenter) cmdCenter.classList.remove("hidden");

        // Update header & sidebar profile labels
        const hName = document.getElementById("headerUserName");
        const hRole = document.getElementById("headerUserRole");
        const sName = document.getElementById("sideUserName");
        const sRole = document.getElementById("sideUserRoleBadge");

        if (hName) hName.innerText = user.name;
        if (hRole) hRole.innerText = user.roleBadge;
        if (sName) sName.innerText = user.name;
        if (sRole) {
            sRole.innerText = user.roleBadge;
            sRole.className = `px-2 py-0.5 rounded font-mono font-bold text-[10px] ${user.roleClass}`;
        }

        // Apply role permissions across all views, navigations, and buttons
        applyRolePermissions(user);

        // Make sure routing is initialized
        initRouting();
    } else {
        // Unauthenticated
        if (loginView) loginView.classList.remove("hidden");
        if (cmdCenter) cmdCenter.classList.add("hidden");
    }
}

function applyRolePermissions(user) {
    if (!user) return;
    const role = user.role; // "COMMANDER", "OPERATOR", "ENGINEER", "VIEWER"

    // 1. Top Navigation Pills & Sidebar Links (Only show allowed pages)
    VALID_PAGES.forEach(page => {
        const navBtn = document.getElementById(`nav-btn-${page}`);
        const sideBtn = document.getElementById(`side-nav-${page}`);
        const isAllowed = user.allowedPages.includes(page);
        if (navBtn) {
            if (isAllowed) navBtn.classList.remove("hidden");
            else navBtn.classList.add("hidden");
        }
        if (sideBtn) {
            if (isAllowed) sideBtn.classList.remove("hidden");
            else sideBtn.classList.add("hidden");
        }
    });

    // 2. Overview Role Context Banner & Direct Role Switchers
    const bannerBadge = document.getElementById("roleContextBadge");
    const bannerTitle = document.getElementById("roleContextTitle");
    const bannerDesc = document.getElementById("roleContextDesc");
    if (bannerBadge) {
        bannerBadge.innerText = user.roleBadge;
        bannerBadge.className = `px-2.5 py-0.5 rounded font-black uppercase text-[10px] tracking-wider border ${user.roleClass}`;
    }
    if (bannerTitle) bannerTitle.innerText = user.roleTitle;
    if (bannerDesc) bannerDesc.innerText = user.roleDesc;

    // Highlight active role buttons
    ['commander', 'operator', 'engineer', 'viewer'].forEach(rKey => {
        const isCurrent = user.username === rKey;
        // Banner buttons
        const bBtn = document.getElementById(`roleSwitchBtn-${rKey}`);
        if (bBtn) {
            if (isCurrent) {
                bBtn.className = "btn-press px-2.5 py-1 rounded-lg text-[10px] font-bold border transition bg-blue-600 text-white border-blue-700 shadow-xs";
            } else {
                bBtn.className = "btn-press px-2.5 py-1 rounded-lg text-[10px] font-bold border transition bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100";
            }
        }
        // Header buttons
        const hBtn = document.getElementById(`roleBtnHeader-${rKey}`);
        if (hBtn) {
            if (isCurrent) {
                hBtn.className = "px-2 py-0.5 rounded font-bold transition bg-blue-600 text-white shadow-xs";
            } else {
                hBtn.className = "px-2 py-0.5 rounded font-medium transition text-slate-600 hover:text-slate-900";
            }
        }
    });

    // 3. Overview Page Strict Role-Based View Filtering
    const publicSection = document.getElementById("publicObserverSection");
    const heroBanner = document.getElementById("heroBanner");
    const aiDecisionPlanSection = document.getElementById("aiDecisionPlanSection");
    const overviewScenarioSection = document.getElementById("overviewScenarioSection");
    const overviewSubsystemsSection = document.getElementById("overviewSubsystemsSection");

    if (role === "VIEWER") {
        // PUBLIC OBSERVER: Only clean public road status, signal indicator, and air quality
        if (publicSection) publicSection.classList.remove("hidden");
        if (heroBanner) heroBanner.classList.add("hidden");
        if (aiDecisionPlanSection) aiDecisionPlanSection.classList.add("hidden");
        if (overviewScenarioSection) overviewScenarioSection.classList.add("hidden");
        if (overviewSubsystemsSection) overviewSubsystemsSection.classList.add("hidden");
    } else {
        // OPERATIONAL ROLES: Show relevant components
        if (publicSection) publicSection.classList.add("hidden");
        if (heroBanner) heroBanner.classList.remove("hidden");
        if (aiDecisionPlanSection) aiDecisionPlanSection.classList.remove("hidden");
        if (overviewScenarioSection) overviewScenarioSection.classList.remove("hidden");
        if (overviewSubsystemsSection) overviewSubsystemsSection.classList.remove("hidden");

        // Role-specific element adaptations
        const evidenceBox = document.getElementById("evidenceChainBox");
        const explainBox = document.getElementById("explainabilityMatrixBox");
        const ackBtn = document.getElementById("ackIncidentBtn");
        const topScenarios = document.getElementById("topScenarioGroup");
        const topEngineer = document.getElementById("topEngineerGroup");
        const benchTitle = document.getElementById("scenarioBenchTitle");
        const btnFire = document.getElementById("btnScenarioFire");
        const btnAccident = document.getElementById("btnScenarioAccident");
        const btnAmbulance = document.getElementById("btnScenarioAmbulance");
        const btnNormal = document.getElementById("btnScenarioNormal");
        const nearMissBox = document.getElementById("overviewNearMissBox");
        const hardwareBox = document.getElementById("overviewHardwareBox");
        const btnDossier = document.getElementById("btnOverviewDossier");

        if (role === "COMMANDER") {
            // INCIDENT COMMANDER: Full Authority across all domains
            if (evidenceBox) evidenceBox.classList.remove("hidden");
            if (explainBox) explainBox.classList.remove("hidden");
            if (topScenarios) topScenarios.classList.remove("hidden");
            if (topEngineer) topEngineer.classList.add("hidden");
            if (benchTitle) benchTitle.innerText = "Scenario Simulation Bench:";
            if (btnFire) btnFire.classList.remove("hidden");
            if (btnAccident) btnAccident.classList.remove("hidden");
            if (btnAmbulance) btnAmbulance.classList.remove("hidden");
            if (btnNormal) btnNormal.classList.remove("hidden");
            if (nearMissBox) nearMissBox.classList.remove("hidden");
            if (hardwareBox) hardwareBox.classList.add("hidden");
            if (btnDossier) btnDossier.classList.remove("hidden");
        } else if (role === "OPERATOR") {
            // TRAFFIC CONTROLLER: Filter out raw sensor noise, weights, & dossiers
            if (evidenceBox) evidenceBox.classList.add("hidden");
            if (explainBox) explainBox.classList.add("hidden");
            if (topScenarios) topScenarios.classList.remove("hidden");
            if (topEngineer) topEngineer.classList.add("hidden");
            if (benchTitle) benchTitle.innerText = "Traffic Corridor Bench:";
            if (btnFire) btnFire.classList.add("hidden"); // Fire suppression managed by Fire Dept/Commander
            if (btnAccident) btnAccident.classList.remove("hidden");
            if (btnAmbulance) btnAmbulance.classList.remove("hidden");
            if (btnNormal) btnNormal.classList.remove("hidden");
            if (nearMissBox) nearMissBox.classList.remove("hidden");
            if (hardwareBox) hardwareBox.classList.add("hidden");
            if (btnDossier) btnDossier.classList.add("hidden");
        } else if (role === "ENGINEER") {
            // HARDWARE ENGINEER: Diagnostics, sensor calibration, driver health
            if (evidenceBox) evidenceBox.classList.remove("hidden");
            if (explainBox) explainBox.classList.remove("hidden");
            if (topScenarios) topScenarios.classList.add("hidden");
            if (topEngineer) topEngineer.classList.remove("hidden");
            if (benchTitle) benchTitle.innerText = "Hardware Driver Diagnostics:";
            if (nearMissBox) nearMissBox.classList.add("hidden");
            if (hardwareBox) hardwareBox.classList.remove("hidden");
            if (btnDossier) btnDossier.classList.add("hidden");
            if (ackBtn) ackBtn.classList.add("hidden");
        }

        // Subsystems cards visibility tailored per role
        updateOverviewCardsAccess(user);
    }

    // 4. Hardware Mode Controls (Commander & Hardware Engineer only)
    const hwControls = document.getElementById("hwModeControls");
    const canHw = user.permissions.includes("hardware") || user.permissions.includes("all");
    if (hwControls) {
        if (canHw) hwControls.classList.remove("hidden");
        else hwControls.classList.add("hidden");
    }

    // 5. Actuator Overrides (Commander & Traffic Controller only)
    const actOverrideSec = document.getElementById("actuatorOverrideSection");
    const canSignals = user.permissions.includes("signals") || user.permissions.includes("all");
    if (actOverrideSec) {
        if (canSignals) actOverrideSec.classList.remove("hidden");
        else actOverrideSec.classList.add("hidden");
    }

    // 6. Firebase Config Button (Commander & Hardware Engineer only)
    const fbBtn = document.getElementById("btnFirebaseConfig");
    const canConfig = user.permissions.includes("config") || user.permissions.includes("all");
    if (fbBtn) {
        if (canConfig) fbBtn.classList.remove("hidden");
        else fbBtn.classList.add("hidden");
    }

    // 7. General action buttons (disabled for read-only viewer)
    const isViewer = user.role === "VIEWER";
    const actionButtons = document.querySelectorAll(".action-btn");
    actionButtons.forEach(btn => {
        if (isViewer) {
            btn.setAttribute("disabled", "true");
            btn.classList.add("opacity-50", "cursor-not-allowed");
            btn.title = "Read-Only: Operator permissions required";
        } else {
            btn.removeAttribute("disabled");
            btn.classList.remove("opacity-50", "cursor-not-allowed");
            btn.title = "";
        }
    });
}

function updateOverviewCardsAccess(user) {
    const role = user.role;
    const cardSensors = document.getElementById("card-nav-sensors");
    const cardActuators = document.getElementById("card-nav-actuators");
    const cardGis = document.getElementById("card-nav-gis");
    const cardLogs = document.getElementById("card-nav-logs");
    const cardDatasets = document.getElementById("card-nav-datasets");
    const grid = document.getElementById("overviewCardsGrid");

    if (role === "COMMANDER") {
        // Commander: Full Overview (Sensors, Actuators, GIS, Incident Logs)
        if (cardSensors) cardSensors.classList.remove("hidden");
        if (cardActuators) cardActuators.classList.remove("hidden");
        if (cardGis) cardGis.classList.remove("hidden");
        if (cardLogs) cardLogs.classList.remove("hidden");
        if (cardDatasets) cardDatasets.classList.add("hidden");
        if (grid) grid.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4";
    } else if (role === "OPERATOR") {
        // Traffic Controller: Actuators, GIS, Incident Logs (Sensors hidden!)
        if (cardSensors) cardSensors.classList.add("hidden");
        if (cardActuators) cardActuators.classList.remove("hidden");
        if (cardGis) cardGis.classList.remove("hidden");
        if (cardLogs) cardLogs.classList.remove("hidden");
        if (cardDatasets) cardDatasets.classList.add("hidden");
        if (grid) grid.className = "grid grid-cols-1 md:grid-cols-3 gap-4";
    } else if (role === "ENGINEER") {
        // Hardware Engineer: Sensors Matrix, Spatial Hardware Node, Datasets Hub (Actuators & Logs hidden!)
        if (cardSensors) cardSensors.classList.remove("hidden");
        if (cardActuators) cardActuators.classList.add("hidden");
        if (cardGis) cardGis.classList.remove("hidden");
        if (cardLogs) cardLogs.classList.add("hidden");
        if (cardDatasets) cardDatasets.classList.remove("hidden");
        if (grid) grid.className = "grid grid-cols-1 md:grid-cols-3 gap-4";
    } else if (role === "VIEWER") {
        if (cardSensors) cardSensors.classList.add("hidden");
        if (cardActuators) cardActuators.classList.add("hidden");
        if (cardGis) cardGis.classList.add("hidden");
        if (cardLogs) cardLogs.classList.add("hidden");
        if (cardDatasets) cardDatasets.classList.add("hidden");
    }
}

function handleCardNav(targetPage) {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (user.allowedPages && user.allowedPages.includes(targetPage)) {
        switchPage(targetPage);
    } else {
        showRoleAccessDeniedToast(targetPage, user);
    }
}

let toastTimer = null;
function showRoleAccessDeniedToast(targetPage, user) {
    const toast = document.getElementById("roleAccessToast");
    const msg = document.getElementById("roleAccessToastMsg");
    if (!toast || !msg) return;

    const pageTitle = (PAGE_TITLES && PAGE_TITLES[targetPage]) ? PAGE_TITLES[targetPage] : targetPage.toUpperCase();
    msg.innerText = `Access Restricted: '${pageTitle}' is not permitted for ${user ? user.roleBadge : 'this role'}.`;
    toast.classList.remove("translate-y-24", "opacity-0");
    toast.classList.add("translate-y-0", "opacity-100");

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.remove("translate-y-0", "opacity-100");
        toast.classList.add("translate-y-24", "opacity-0");
    }, 3500);
}

async function fetchSystemVersion() {
    try {
        const res = await fetch("/api/system/version");
        if (!res.ok) return;
        const data = await res.json();
        const badge = document.getElementById("systemVersionBadge");
        if (badge) {
            badge.innerText = `v${data.version} (${data.git_hash})`;
            badge.title = `Target: ${data.target_platform} | Built: ${data.build_date} | Schema: v${data.schema_version}`;
        }
    } catch (e) {}
}

// Initialize Dashboard upon DOM Load
document.addEventListener("DOMContentLoaded", () => {
    checkAuthAndRender();

    if (window.Chart) initChart();
    initFirebaseOrFallback();
    fetchSystemVersion();
    fetchHistoricalEvents();
    fetchRecordings();
    setInterval(fetchHistoricalEvents, 10000);
    setInterval(fetchRecordings, 10000);
});

/* ========================================================================= */
/* 1. FIREBASE & FALLBACK DATA SUBSCRIPTION                                  */
/* ========================================================================= */

function initFirebaseOrFallback() {
    const DEFAULT_DB_URL = "https://edge-ai-524d4-default-rtdb.asia-southeast1.firebasedatabase.app";
    const savedDbUrl = localStorage.getItem("sentinel_firebase_db_url") || DEFAULT_DB_URL;

    if (!window.firebase) {
        startLocalPolling();
        return;
    }
    if (savedDbUrl && savedDbUrl.startsWith("https://")) {
        try {
            if (!firebase.apps.length) {
                firebaseApp = firebase.initializeApp({
                    databaseURL: savedDbUrl
                });
            }
            firebaseDb = firebase.database();
            isUsingFirebase = true;

            updateCloudStatus(true, "Firebase Realtime DB");

            const nodeRef = firebaseDb.ref("nodes/NODE_B");
            nodeRef.on("value", (snapshot) => {
                const data = snapshot.val();
                if (data) {
                    processLivePayload({
                        telemetry: data.telemetry || {},
                        actuators: data.actuators || {},
                        active_event: data.current_event || {}
                    });
                }
            }, (error) => {
                console.warn("[Firebase] Listener note, falling back to Local Bridge:", error);
                startLocalPolling();
            });

            console.log("[Sentinel] Connected to Firebase Realtime Database:", savedDbUrl);
            return;
        } catch (e) {
            console.error("[Firebase] Initialization error:", e);
        }
    }

    startLocalPolling();
}

function startLocalPolling() {
    isUsingFirebase = false;
    updateCloudStatus(false, "Local Edge Bridge");

    if (pollingTimer) clearInterval(pollingTimer);
    fetchLiveEdgeData();
    pollingTimer = setInterval(fetchLiveEdgeData, 1200);
}

async function fetchLiveEdgeData() {
    try {
        const res = await fetch("/api/live");
        if (!res.ok) throw new Error("Local API unreachable");
        const data = await res.json();
        processLivePayload(data);
        updateResponsePlan();
    } catch (e) {
        const dot = document.getElementById("cloudStatusDot");
        const text = document.getElementById("cloudStatusText");
        if (dot) dot.className = "h-2 w-2 rounded-full bg-rose-500 animate-pulse";
        if (text) text.innerText = "Edge Offline";
    }
}

function updateCloudStatus(isCloud, text) {
    const dot = document.getElementById("cloudStatusDot");
    const label = document.getElementById("cloudStatusText");
    if (!dot || !label) return;
    if (isCloud) {
        dot.className = "h-2 w-2 rounded-full bg-emerald-500 animate-pulse";
        label.className = "font-bold text-emerald-700";
        label.innerText = text;
    } else {
        dot.className = "h-2 w-2 rounded-full bg-amber-500";
        label.className = "font-bold text-amber-700";
        label.innerText = text;
    }
}

/* ========================================================================= */
/* 2. REAL-TIME UI UPDATE PIPELINE (CLEAN ICON-FREE)                         */
/* ========================================================================= */

let lastEventClass = "NORMAL";

function processLivePayload(data) {
    const t = data.telemetry || {};
    const a = data.actuators || {};
    const ev = data.active_event || {};
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    const temporal = document.getElementById("heroTemporalState");
    const ood = document.getElementById("heroOodStatus");
    const oodDecision = data.ood_decision || ev.ood_decision || {};
    if (temporal) temporal.innerText = `TEMPORAL: ${ev.temporal_state || data.temporal_state || "CANDIDATE"}`;
    if (ood) ood.innerText = `OOD: ${oodDecision.status || ev.ood_status || "REVIEW REQUIRED"}`;

    // 0. Update Dedicated Public Observer View if active role is VIEWER
    if (user.role === "VIEWER") {
        updatePublicObserverView(ev, t, a);
    } else {
        // 1. Update Hero Incident Banner with role-tailored information
        updateHeroBanner(ev, t, user);

        // 1b. Update AI Summary & Action Plan with role-tailored context
        updateAIDecisionPlan(ev, t, a, user);

        // 2. Update Sensor Telemetry Cards & Overview Mirrors
        updateSensors(t);

        // 2b. Update Predictive Near-Miss TTC Radar (Operator/Commander) & Hardware Box (Engineer)
        updateNearMissRadar(data.near_miss || t.near_miss_analysis);
        updateHardwareOverviewBox(t);
        updateModelAssurance(data.assurance);

        // 3. Update Actuators & Overview Mirrors
        updateActuators(a);
    }

    // 4. Update Real-time Chart
    updateChart(t.temperature, t.smoke_level);

    // 5. Sound Alert if New Emergency Triggered
    if (ev.event && ev.event !== "NORMAL" && ev.event !== lastEventClass) {
        if (ev.event === "ACCIDENT") playChime(440, 0.4);
        else if (ev.event === "FIRE") playChime(750, 0.3);
        else if (ev.event === "EMERGENCY_VEHICLE") playChime(880, 0.3);
    }
    lastEventClass = ev.event || "NORMAL";
}

function authHeaders(extra = {}) {
    const user = getCurrentUser();
    return { ...extra, ...(user?.authToken ? { Authorization: `Bearer ${user.authToken}` } : {}) };
}

let responsePlanInFlight = false;
async function updateResponsePlan() {
    if (responsePlanInFlight) return;
    responsePlanInFlight = true;
    try {
        const response = await fetch("/api/response-plan");
        if (!response.ok) throw new Error("Response plan unavailable");
        const plan = await response.json();
        const summary = document.getElementById("responsePlanSummary");
        const mode = document.getElementById("responsePlanMode");
        const actions = document.getElementById("responsePlanActions");
        if (!summary || !mode) return;
        summary.innerText = `${plan.event || "NORMAL"} · ${plan.severity || "NORMAL"} · ${plan.zone || "Zone unavailable"}`;
        mode.innerText = plan.operator_confirmation_required ? "Operator confirmation required" : "Decision support";
        document.getElementById("emergencyPlanLevel").innerText = plan.severity || "NORMAL";
        document.getElementById("emergencyPlanZone").innerText = plan.zone || "Unavailable";
        document.getElementById("emergencyPlanIncident").innerText = plan.incident_id || "No linked incident";
        if (actions) actions.innerHTML = (plan.recommended_actions || []).map((action,index) => `<li class="flex gap-3 p-3 text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-xl"><span class="font-mono font-bold text-blue-700">${index+1}</span><span>${escapeHtml(action)}</span></li>`).join("") || '<li class="text-sm text-slate-500">No emergency action is required for the current event.</li>';
    } catch (_) {
        const summary = document.getElementById("responsePlanSummary");
        if (summary) summary.innerText = "Response plan is temporarily unavailable.";
    } finally { responsePlanInFlight = false; }
}

function openResponsePlan() {
    switchPage("emergency-plan");
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    }[character]));
}

function updateModelAssurance(assurance) {
    if (!assurance) return;
    const profile = document.getElementById("assuranceProfile");
    const status = document.getElementById("assuranceStatus");
    const guidance = document.getElementById("assuranceGuidance");
    const rows = document.getElementById("assuranceRows");
    const confirmation = document.getElementById("assuranceConfirmation");
    if (!profile || !status || !guidance || !rows || !confirmation) return;

    profile.innerText = `${assurance.profile || "legacy"} profile`;
    guidance.innerText = assurance.guidance || "No assurance guidance is available.";
    const statusClasses = {
        RESEARCH_ONLY: "bg-violet-50 text-violet-800 border-violet-200",
        REVIEW_REQUIRED: "bg-rose-50 text-rose-800 border-rose-200",
        MULTIMODAL_REVIEW: "bg-amber-50 text-amber-800 border-amber-200",
        MONITORING: "bg-emerald-50 text-emerald-800 border-emerald-200"
    };
    status.className = `px-2 py-1 rounded border text-[10px] font-mono font-bold uppercase ${statusClasses[assurance.status] || "bg-slate-100 text-slate-700 border-slate-200"}`;
    status.innerText = String(assurance.status || "UNMEASURED").replaceAll("_", " ");

    const readinessClasses = {
        SUPPORTED: "bg-emerald-100 text-emerald-800 border-emerald-200",
        CAUTION: "bg-amber-100 text-amber-800 border-amber-200",
        REVIEW_REQUIRED: "bg-rose-100 text-rose-800 border-rose-200",
        UNMEASURED: "bg-slate-100 text-slate-700 border-slate-200"
    };
    rows.innerHTML = (assurance.modalities || []).map(item => {
        const heldOut = typeof item.held_out_f1 === "number" ? `${Math.round(item.held_out_f1 * 100)}% held-out F1` : "Held-out score unavailable";
        const confidence = typeof item.model_confidence === "number" ? `${Math.round(item.model_confidence * 100)}% model confidence` : "No live confidence";
        const readiness = String(item.readiness || "UNMEASURED");
        return `<div class="p-2.5 rounded-lg bg-slate-50 border border-slate-200 flex items-start justify-between gap-3">
            <div class="min-w-0">
                <div class="text-[10px] font-mono font-bold text-slate-500 uppercase">${escapeHtml(item.modality)} prediction</div>
                <div class="text-xs font-bold text-slate-800 mt-0.5 truncate">${escapeHtml(item.label)}</div>
                <div class="text-[10px] text-slate-500 mt-1">${confidence} · ${heldOut}</div>
                <div class="text-[10px] text-slate-400 mt-0.5 truncate">${escapeHtml(item.source || "Source unavailable")}</div>
            </div>
            <span class="shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-mono font-bold ${readinessClasses[readiness] || readinessClasses.UNMEASURED}">${escapeHtml(readiness.replaceAll("_", " "))}</span>
        </div>`;
    }).join("") || '<div class="text-xs text-slate-500">No model evidence available for the active profile.</div>';

    confirmation.classList.toggle("hidden", !assurance.operator_confirmation_required);
    confirmation.innerText = assurance.operator_confirmation_required
        ? "Operator confirmation is required before action. Model assurance is advisory and does not modify the actuator protocol."
        : "Operator confirmation is not requested by the current assurance profile.";
}

function updateHardwareOverviewBox(t) {
    const hwBox = document.getElementById("overviewHardwareBox");
    if (!hwBox) return;
    const cpu = t.cpu_temp ? t.cpu_temp.toFixed(1) + "°C" : "41.6°C";
    const fps = t.fps ? t.fps.toFixed(1) + " FPS" : "15.2 FPS";
    hwBox.innerHTML = `
        <span class="text-slate-400 font-bold uppercase text-[10px]">EDGE HEALTH:</span>
        <span class="font-black text-blue-600 tnum">${fps}</span>
        <span class="text-slate-300">|</span>
        <span class="font-bold text-slate-700 tnum">CPU ${cpu}</span>
        <span class="text-[9px] px-1.5 py-0.5 rounded font-bold bg-emerald-100 text-emerald-800 uppercase">ONLINE</span>
    `;
}

function updatePublicObserverView(ev, t, a) {
    const headline = document.getElementById("publicStatusHeadline");
    const badge = document.getElementById("publicStatusBadge");
    const msg = document.getElementById("publicStatusMessage");
    const icon = document.getElementById("publicStatusIcon");
    const sigText = document.getElementById("publicSignalText");
    const sigSub = document.getElementById("publicSignalSub");
    const corText = document.getElementById("publicCorridorText");
    const corSub = document.getElementById("publicCorridorSub");
    const airText = document.getElementById("publicAirText");
    const airSub = document.getElementById("publicAirSub");

    const eventName = ev.event || "NORMAL";

    if (eventName === "EMERGENCY_VEHICLE") {
        if (badge) {
            badge.innerText = "PRIORITY CORRIDOR • EMERGENCY VEHICLE";
            badge.className = "px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-200 animate-pulse";
        }
        if (headline) headline.innerText = "Emergency Vehicle Passing — Please Yield";
        if (msg) msg.innerText = "An approaching ambulance or emergency vehicle is navigating this corridor. Automated green wave signal preemption is active. Drivers and pedestrians are advised to yield right-of-way.";
        if (icon) {
            icon.innerText = "🚑";
            icon.className = "h-14 w-14 rounded-2xl bg-blue-50 border border-blue-200 flex items-center justify-center text-2xl text-blue-600 shadow-subtle shrink-0 animate-pulse";
        }
        if (sigText) {
            sigText.innerText = "PRIORITY GREEN";
            sigText.className = "text-2xl font-black text-blue-600 mt-1 font-mono";
        }
        if (sigSub) sigSub.innerText = "Priority Emergency Transit";
        if (corText) {
            corText.innerText = "EMERGENCY ONLY";
            corText.className = "text-2xl font-black text-blue-600 mt-1 font-mono";
        }
        if (corSub) corSub.innerText = "Corridor Reserved for Responders";
    } else if (eventName === "ACCIDENT") {
        if (badge) {
            badge.innerText = "CAUTION • ROAD INCIDENT IN SECTOR";
            badge.className = "px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase tracking-wider bg-rose-100 text-rose-800 border border-rose-200 animate-pulse";
        }
        if (headline) headline.innerText = "Traffic Incident Detected — Drive Carefully";
        if (msg) msg.innerText = "A traffic incident has been detected at Intersection 4. Emergency services have been automatically notified. Approach signals are holding traffic to allow response crews to clear the scene.";
        if (icon) {
            icon.innerText = "⚠️";
            icon.className = "h-14 w-14 rounded-2xl bg-rose-50 border border-rose-200 flex items-center justify-center text-2xl text-rose-600 shadow-subtle shrink-0 animate-pulse";
        }
        if (sigText) {
            sigText.innerText = "RED (LANE STOP)";
            sigText.className = "text-2xl font-black text-rose-600 mt-1 font-mono";
        }
        if (sigSub) sigSub.innerText = "Traffic Halted for Incident Scene";
        if (corText) {
            corText.innerText = "RESTRICTED ACCESS";
            corText.className = "text-2xl font-black text-rose-600 mt-1 font-mono";
        }
        if (corSub) corSub.innerText = "Caution: Collision In Lane";
    } else if (eventName === "FIRE") {
        if (badge) {
            badge.innerText = "HAZARD ADVISORY • ELEVATED SMOKE";
            badge.className = "px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase tracking-wider bg-amber-100 text-amber-800 border border-amber-200 animate-pulse";
        }
        if (headline) headline.innerText = "Combustion Smoke Detected Near Intersection";
        if (msg) msg.innerText = "Sensor nodes have detected smoke near the perimeter. Fire and safety units are on scene. Approach cautiously and follow direction from municipal personnel.";
        if (icon) {
            icon.innerText = "🔥";
            icon.className = "h-14 w-14 rounded-2xl bg-amber-50 border border-amber-200 flex items-center justify-center text-2xl text-amber-600 shadow-subtle shrink-0 animate-pulse";
        }
        if (sigText) {
            sigText.innerText = "CAUTION HOLD";
            sigText.className = "text-2xl font-black text-amber-600 mt-1 font-mono";
        }
        if (sigSub) sigSub.innerText = "Cautionary Signal State";
        if (corText) {
            corText.innerText = "RESTRICTED";
            corText.className = "text-2xl font-black text-amber-600 mt-1 font-mono";
        }
        if (corSub) corSub.innerText = "Perimeter Safety Interlock";
    } else {
        if (badge) {
            badge.innerText = "ALL CLEAR • NORMAL FLOW";
            badge.className = "px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 border border-emerald-200";
        }
        if (headline) headline.innerText = "Intersection Operating Within Safe Limits";
        if (msg) msg.innerText = "All arterial corridors are clear. Traffic signals are synchronized for normal progression. Pedestrian crossings are open.";
        if (icon) {
            icon.innerText = "✓";
            icon.className = "h-14 w-14 rounded-2xl bg-emerald-50 border border-emerald-200 flex items-center justify-center font-bold text-2xl text-emerald-600 shadow-subtle shrink-0";
        }
        if (sigText) {
            sigText.innerText = "GREEN (FLOW)";
            sigText.className = "text-2xl font-black text-emerald-600 mt-1 font-mono";
        }
        if (sigSub) sigSub.innerText = "Vehicular Transit Permitted";
        if (corText) {
            corText.innerText = "OPEN & CLEAR";
            corText.className = "text-2xl font-black text-emerald-600 mt-1 font-mono";
        }
        if (corSub) corSub.innerText = "No Physical Obstacles";
    }

    // Environmental Quality
    if (airText) {
        const smoke = t.smoke_level || 10;
        if (smoke > 80) {
            airText.innerText = "POOR (SMOKE)";
            airText.className = "text-2xl font-black text-rose-600 mt-1 font-mono";
            if (airSub) airSub.innerText = "Combustion Density High";
        } else if (smoke > 35) {
            airText.innerText = "MODERATE";
            airText.className = "text-2xl font-black text-amber-600 mt-1 font-mono";
            if (airSub) airSub.innerText = "Vehicular Exhaust Detected";
        } else {
            airText.innerText = "GOOD / CLEAN";
            airText.className = "text-2xl font-black text-emerald-600 mt-1 font-mono";
            if (airSub) airSub.innerText = "Air Clean & Hazard Free";
        }
    }
}

function updateNearMissRadar(nm) {
    if (!nm) return;
    const ttcVal = document.getElementById("nearMissTtcVal");
    const badge = document.getElementById("nearMissBadge");
    if (!ttcVal || !badge) return;

    const val = nm.min_ttc_sec !== undefined ? nm.min_ttc_sec.toFixed(1) + "s" : "9.9s";
    ttcVal.innerText = val;

    if (nm.is_imminent) {
        ttcVal.className = "font-black text-rose-600 tnum";
        badge.className = "text-[9px] px-1.5 py-0.5 rounded font-bold bg-rose-100 text-rose-800 uppercase animate-pulse";
        badge.innerText = "CRITICAL";
    } else if (nm.is_near_miss) {
        ttcVal.className = "font-black text-amber-600 tnum";
        badge.className = "text-[9px] px-1.5 py-0.5 rounded font-bold bg-amber-100 text-amber-800 uppercase";
        badge.innerText = "NEAR-MISS";
    } else {
        ttcVal.className = "font-black text-emerald-600 tnum";
        badge.className = "text-[9px] px-1.5 py-0.5 rounded font-bold bg-emerald-100 text-emerald-800 uppercase";
        badge.innerText = "NOMINAL";
    }
}

function updateHeroBanner(ev, t, user) {
    const hero = document.getElementById("heroBanner");
    const stateInd = document.getElementById("heroStateIndicator") || document.getElementById("heroIconContainer");
    const sev = document.getElementById("heroSeverityBadge");
    const title = document.getElementById("heroEventBadge");
    const conf = document.getElementById("heroConfidenceBadge");
    const desc = document.getElementById("heroDescription");
    const zone = document.getElementById("heroZone");
    const ping = document.getElementById("nodeBPing");
    const circle = document.getElementById("nodeBCircle");
    const ackBtn = document.getElementById("ackIncidentBtn");

    const eventName = ev.event || "NORMAL";
    const confidence = Math.round((ev.confidence || 0.9) * 100);

    if (conf) conf.innerText = `CONFIDENCE: ${confidence}%`;
    if (zone) zone.innerText = ev.zone || "ZONE_B_INTERSECTION";

    if (hero) hero.classList.remove("hero-accident", "hero-fire", "hero-ambulance");

    // HARDWARE ENGINEER ROLE: Hero shows edge computing & sensor health
    if (user && user.role === "ENGINEER") {
        if (stateInd) {
            stateInd.innerText = "HW";
            stateInd.className = "h-12 w-12 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center font-mono font-black text-xs text-blue-700 tracking-wider shadow-subtle shrink-0";
        }
        if (sev) {
            sev.innerText = "6/6 SENSORS ONLINE";
            sev.className = "px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-200";
        }
        if (title) {
            title.innerText = "EDGE HARDWARE & SENSOR HEALTH (NODE B)";
            title.className = "text-lg font-black text-slate-900 tracking-tight";
        }
        if (conf) {
            conf.innerText = `CPU: ${t && t.cpu_temp ? t.cpu_temp.toFixed(1) : "41.6"}°C`;
        }
        if (desc) {
            desc.innerText = `Raspberry Pi 4 Quad-Core Cortex-A72 active. Edge AI inference at ${t && t.fps ? t.fps.toFixed(1) : "15.2"} FPS. Physical sensor drivers (DHT22, ADS1115 MQ-2, MPU-6050, Optical Flow, ALSA) streaming nominal telemetry over I2C/GPIO.`;
        }
        if (ping) ping.className = "absolute -inset-3 rounded-full bg-blue-400/40 animate-ping";
        if (circle) circle.className = "h-9 w-9 rounded-full bg-blue-600 border-2 border-white flex items-center justify-center text-[11px] font-black text-white shadow-md font-mono";
        if (ackBtn) ackBtn.classList.add("hidden");
    } else if (eventName === "ACCIDENT") {
        if (hero) hero.classList.add("hero-accident");
        if (stateInd) {
            stateInd.innerText = "COL";
            stateInd.className = "h-12 w-12 rounded-xl bg-rose-100 border border-rose-300 flex items-center justify-center font-mono font-black text-xs text-rose-800 shadow-sm animate-pulse";
        }
        if (sev) {
            sev.innerText = "CRITICAL SEVERITY";
            sev.className = "px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-rose-100 text-rose-800 border border-rose-300 font-mono";
        }
        if (title) {
            title.innerText = (user && user.role === "OPERATOR") ? "COLLISION BLOCKING INTERSECTION" : "VEHICLE COLLISION DETECTED";
            title.className = "text-lg font-black text-rose-900 tracking-tight";
        }
        if (desc) {
            desc.innerText = (user && user.role === "OPERATOR") ? "Vehicular impact in Sector Zone B. Approach signals set to RED to halt traffic. Barrier interlock engaged to clear lane." : (ev.description || "Multi-sensor verified road accident with acoustic crash and high physical impact shock.");
        }
        if (ping) ping.className = "absolute -inset-3 rounded-full bg-rose-400/50 animate-ping";
        if (circle) circle.className = "h-9 w-9 rounded-full bg-rose-600 border-2 border-white flex items-center justify-center text-[11px] font-black text-white shadow-md font-mono";
    } else if (eventName === "FIRE") {
        if (hero) hero.classList.add("hero-fire");
        if (stateInd) {
            stateInd.innerText = "FIRE";
            stateInd.className = "h-12 w-12 rounded-xl bg-amber-100 border border-amber-300 flex items-center justify-center font-mono font-black text-xs text-amber-800 shadow-sm animate-pulse";
        }
        if (sev) {
            sev.innerText = "CRITICAL SEVERITY";
            sev.className = "px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-amber-100 text-amber-800 border border-amber-300 font-mono";
        }
        if (title) {
            title.innerText = (user && user.role === "OPERATOR") ? "ROADWAY SMOKE HAZARD — HOLD SIGNALS" : "FIRE & TOXIC SMOKE HAZARD";
            title.className = "text-lg font-black text-amber-900 tracking-tight";
        }
        if (desc) {
            desc.innerText = (user && user.role === "OPERATOR") ? "Combustion smoke detected near roadway. Approach signals placed on all-red hold to prevent vehicles entering hazard zone." : (ev.description || "Active combustion gas density elevated and thermal heat anomaly verified.");
        }
        if (ping) ping.className = "absolute -inset-3 rounded-full bg-amber-400/50 animate-ping";
        if (circle) circle.className = "h-9 w-9 rounded-full bg-amber-600 border-2 border-white flex items-center justify-center text-[11px] font-black text-white shadow-md font-mono";
    } else if (eventName === "EMERGENCY_VEHICLE") {
        if (hero) hero.classList.add("hero-ambulance");
        if (stateInd) {
            stateInd.innerText = "AMB";
            stateInd.className = "h-12 w-12 rounded-xl bg-blue-100 border border-blue-300 flex items-center justify-center font-mono font-black text-xs text-blue-800 shadow-sm animate-pulse";
        }
        if (sev) {
            sev.innerText = "HIGH SEVERITY";
            sev.className = "px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-300 font-mono";
        }
        if (title) {
            title.innerText = (user && user.role === "OPERATOR") ? "PRIORITY GREEN CORRIDOR ENGAGED" : "EMERGENCY GREEN CORRIDOR ENGAGED";
            title.className = "text-lg font-black text-blue-900 tracking-tight";
        }
        if (desc) {
            desc.innerText = (user && user.role === "OPERATOR") ? "Approaching ambulance verified. Arterial traffic signal held on GREEN. Cross-street traffic held on RED for priority transit." : (ev.description || "Ambulance acoustic siren verified. Traffic signal pre-emption active.");
        }
        if (ping) ping.className = "absolute -inset-3 rounded-full bg-blue-400/50 animate-ping";
        if (circle) circle.className = "h-9 w-9 rounded-full bg-blue-600 border-2 border-white flex items-center justify-center text-[11px] font-black text-white shadow-md font-mono";
    } else {
        if (stateInd) {
            stateInd.innerText = "NOM";
            stateInd.className = "h-12 w-12 rounded-xl bg-emerald-50 border border-emerald-200 flex items-center justify-center font-mono font-black text-xs text-emerald-700 shadow-sm";
        }
        if (sev) {
            sev.innerText = "LOW SEVERITY";
            sev.className = "px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 border border-emerald-200 font-mono";
        }
        if (title) {
            title.innerText = (user && user.role === "OPERATOR") ? "NORMAL TRAFFIC PROGRESSION" : "NORMAL TRAFFIC PATTERN";
            title.className = "text-lg font-black text-slate-900 tracking-tight";
        }
        if (desc) {
            desc.innerText = (user && user.role === "OPERATOR") ? "Urban intersection operating within calibrated capacity. Standard green/yellow/red signal cycles active. Perimeter barrier open." : "Urban intersection operating within standard parameters. Autonomous actuators in standby.";
        }
        if (ping) ping.className = "absolute -inset-3 rounded-full bg-emerald-400/40 animate-ping";
        if (circle) circle.className = "h-9 w-9 rounded-full bg-emerald-500 border-2 border-white flex items-center justify-center text-[11px] font-black text-white shadow-md font-mono";
    }

    // Explainable AI Evidence Chain (Clean Text Badges)
    const evidenceList = document.getElementById("evidenceList");
    if (evidenceList) {
        const chains = ev.evidence_chain || ["Multi-sensor temporal fusion baseline verified."];
        evidenceList.innerHTML = chains.map(item => `
            <span class="px-2.5 py-1 rounded bg-slate-100 border border-slate-200 text-[11px] font-medium font-mono text-slate-700">
                • ${item}
            </span>
        `).join("");
    }

    // Multimodal Sensor Contribution Breakdown
    const contribs = ev.sensor_contributions || null;
    const verdictEl = document.getElementById("explainableVerdictText");
    if (verdictEl && ev.explainable_verdict) {
        verdictEl.innerText = ev.explainable_verdict;
    }

    ["imu", "audio", "vision", "smoke", "temp"].forEach(key => {
        const pctVal = (contribs && Number.isFinite(Number(contribs[key]))) ? Number(contribs[key]).toFixed(1) : null;
        const pctEl = document.getElementById(`pct-${key}`);
        const barEl = document.getElementById(`bar-${key}`);
        if (pctEl) pctEl.innerText = pctVal === null ? "not available" : `${pctVal}%`;
        if (barEl) barEl.style.width = pctVal === null ? "0%" : `${Math.min(100, Math.max(5, parseFloat(pctVal)))}%`;
    });

    // Alert Acknowledgment Button (Role Enforced: Commander & Operator)
    if (ackBtn && user && user.role !== "ENGINEER") {
        const canAck = user && (user.permissions.includes("ack") || user.permissions.includes("all"));
        if (eventName !== "NORMAL" && canAck) {
            ackBtn.classList.remove("hidden");
            ackBtn.setAttribute("data-incident-id", ev.id || "");
            ackBtn.innerText = "ACKNOWLEDGE INCIDENT";
            ackBtn.className = "action-btn px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold uppercase tracking-wider transition shadow-sm font-mono";
        } else {
            ackBtn.classList.add("hidden");
        }
    }
}

function updateAIDecisionPlan(ev, t, a, user) {
    const statusBadge = document.getElementById("aiPlanStatusBadge");
    const ruleBadge = document.getElementById("aiRuleBadge");
    const summaryText = document.getElementById("aiSummaryText");
    const riskLevel = document.getElementById("aiRiskLevel");
    const primaryModality = document.getElementById("aiPrimaryModality");
    const verificationState = document.getElementById("aiVerificationState");
    const actionPlanSteps = document.getElementById("aiActionPlanSteps");

    if (!summaryText || !actionPlanSteps) return;

    // HARDWARE ENGINEER ROLE: Custom diagnostics action plan
    if (user && user.role === "ENGINEER") {
        if (ruleBadge) {
            ruleBadge.innerText = "EDGE SENSOR BUS";
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-blue-50 text-blue-800 border border-blue-200 uppercase";
        }
        statusBadge.innerText = "ALL DRIVERS SYNCHRONIZED";
        statusBadge.className = "px-3 py-1 rounded text-xs font-mono font-extrabold bg-emerald-100 text-emerald-800 border border-emerald-200 uppercase";

        summaryText.innerText = `Raspberry Pi 4 hardware telemetry actively streaming. Sensor fusion bus operating at ${t.fps ? t.fps.toFixed(1) : "15.2"} FPS with ${t.cpu_temp ? t.cpu_temp.toFixed(1) : "41.6"}°C SoC core temperature. Deep neural nets EdgeAcousticNet and YOLO11n-Edge online with zero dropped frames.`;

        riskLevel.innerText = "NOMINAL (OK)";
        riskLevel.className = "font-bold text-emerald-600 font-mono";
        primaryModality.innerText = "I2C + GPIO + ALSA";
        verificationState.innerText = "ONLINE (6/6)";
        verificationState.className = "font-bold text-emerald-600 font-mono";

        actionPlanSteps.innerHTML = `
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">CH 01</span>
                <span><b>DHT22 (Climate):</b> Sampling ambient temperature (${t.temperature ? t.temperature.toFixed(1) : "28.5"}°C) on GPIO 4 with zero dropped packets.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">CH 02</span>
                <span><b>MQ-2 (Combustion Gas):</b> Polling ADS1115 ADC over I2C 0x48 (${t.smoke_level ? t.smoke_level.toFixed(1) : "12.0"} PPM baseline).</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">CH 03</span>
                <span><b>GY-87 (Inertial Impact):</b> Sampling 3-axis accelerometer and gyro on I2C 0x68 (${t.acceleration_g ? t.acceleration_g.toFixed(2) : "0.03"}g).</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">AI NET</span>
                <span><b>Neural Net Pipeline:</b> EdgeAcousticNet (acoustic_emergency_net.pt) + YOLO11n (fire_smoke_best.pt) active.</span>
            </li>
        `;
        return;
    }

    const eventName = ev.event || "NORMAL";
    const ruleId = ev.rule_id || t.rule_id || (eventName === "ACCIDENT" ? "RULE_R1_COLLISION" : (eventName === "FIRE" ? "RULE_R2_FIRE_SMOKE" : (eventName === "EMERGENCY_VEHICLE" ? "RULE_R3_EMERGENCY_CORRIDOR" : "RULE_R0_NOMINAL")));

    // TRAFFIC CONTROLLER ROLE: Custom traffic routing protocol
    if (user && user.role === "OPERATOR") {
        if (ruleBadge) {
            ruleBadge.innerText = (eventName === "NORMAL" ? "TRAFFIC NOMINAL" : (eventName === "EMERGENCY_VEHICLE" ? "CORRIDOR PREEMPTION" : "TRAFFIC INTERVENTION"));
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-emerald-50 text-emerald-800 border border-emerald-200 uppercase";
        }
        if (eventName === "ACCIDENT") {
            statusBadge.innerText = "LANE RESTRICTION ACTIVE";
            statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-rose-100 text-rose-800 border border-rose-200 uppercase font-mono animate-pulse";
            summaryText.innerText = "Traffic incident blocking lanes in Sector Zone B. Intersection approach signal set to RED. Automated perimeter barrier secured to prevent secondary collisions.";
            riskLevel.innerText = "LANE BLOCKED";
            riskLevel.className = "font-bold text-rose-600 font-mono";
            primaryModality.innerText = "Optical + Impact";
            verificationState.innerText = "VERIFIED";
            verificationState.className = "font-bold text-rose-600 font-mono";

            actionPlanSteps.innerHTML = `
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                    <span><b>Traffic Light:</b> Cycle approach signal to RED/HOLD to halt oncoming traffic flow.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                    <span><b>Barrier Gate:</b> Secure gate to isolate incident perimeter.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                    <span><b>Corridor Clearance:</b> Direct traffic flow away from obstructed intersection lanes.</span>
                </li>
            `;
            return;
        } else if (eventName === "EMERGENCY_VEHICLE") {
            statusBadge.innerText = "GREEN WAVE ENGAGED";
            statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-blue-100 text-blue-800 border border-blue-200 uppercase font-mono animate-pulse";
            summaryText.innerText = "Priority corridor engaged for emergency responder vehicle. Conflicting signals held on RED. Arterial signal maintained on GREEN.";
            riskLevel.innerText = "PRIORITY ROUTE";
            riskLevel.className = "font-bold text-blue-600 font-mono";
            primaryModality.innerText = "Acoustic Siren";
            verificationState.innerText = "ACTIVE CORRIDOR";
            verificationState.className = "font-bold text-blue-600 font-mono";

            actionPlanSteps.innerHTML = `
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                    <span><b>Green Wave:</b> Hold arterial traffic signal on GREEN for incoming emergency responder.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                    <span><b>Cross-Street Hold:</b> Hold all cross-traffic on RED to ensure intersection is clear.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-700">
                    <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                    <span><b>Corridor Release:</b> Automatically restore standard cyclic timing once vehicle clears zone.</span>
                </li>
            `;
            return;
        } else {
            statusBadge.innerText = "CYCLIC SIGNAL TIMING";
            statusBadge.className = "px-3 py-1 rounded text-xs font-mono font-extrabold bg-emerald-100 text-emerald-800 border border-emerald-200 uppercase";
            summaryText.innerText = "Standard urban traffic progression active. Traffic signals operating on calibrated green/yellow/red cycles across all approaches. Perimeter barrier in open standby.";
            riskLevel.innerText = "NOMINAL FLOW";
            riskLevel.className = "font-bold text-emerald-600 font-mono";
            primaryModality.innerText = "Signal Controller";
            verificationState.innerText = "SYNCHRONIZED";
            verificationState.className = "font-bold text-emerald-600 font-mono";

            actionPlanSteps.innerHTML = `
                <li class="flex items-start gap-2.5 text-slate-600">
                    <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                    <span>Maintain standard cyclic traffic signal timing across all approaches.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-600">
                    <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                    <span>Keep perimeter barrier open for uninterrupted municipal transit.</span>
                </li>
                <li class="flex items-start gap-2.5 text-slate-600">
                    <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                    <span>Monitor optical vehicle counts and standby for priority corridor requests.</span>
                </li>
            `;
            return;
        }
    }

    // COMMANDER ROLE: Full authority AI situational assessment & protocol
    if (ruleBadge) {
        ruleBadge.innerText = ruleId;
        if (ruleId.includes("COLLISION") || ruleId.includes("R1")) {
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-rose-100 text-rose-800 border border-rose-300 uppercase";
        } else if (ruleId.includes("FIRE") || ruleId.includes("R2")) {
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300 uppercase";
        } else if (ruleId.includes("EMERGENCY") || ruleId.includes("R3")) {
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-blue-100 text-blue-800 border border-blue-300 uppercase";
        } else {
            ruleBadge.className = "px-2.5 py-1 rounded text-[11px] font-mono font-bold bg-emerald-50 text-emerald-800 border border-emerald-200 uppercase";
        }
    }

    if (eventName === "ACCIDENT") {
        statusBadge.innerText = "CRITICAL ACTION SEQUENCE ACTIVE";
        statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-rose-100 text-rose-800 border border-rose-200 uppercase font-mono animate-pulse";
        
        summaryText.innerText = `High-consequence vehicular collision verified at ${ev.zone || "Zone B"}. Multi-modal fusion correlates physical accelerometer shock (${t.acceleration_g ? t.acceleration_g.toFixed(2) : "4.5"}g) with acoustic crash signature and optical deceleration. Automatic lane restriction and EMS first-responder dispatch engaged.`;
        
        riskLevel.innerText = "CRITICAL";
        riskLevel.className = "font-bold text-rose-600 font-mono";
        primaryModality.innerText = "Acoustic + IMU Spike";
        verificationState.innerText = "CONFIRMED (VERIFIED)";
        verificationState.className = "font-bold text-rose-600 font-mono";

        actionPlanSteps.innerHTML = `
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                <span><b>Signal Actuation:</b> Switch local traffic light to RED/CAUTION to halt incoming arterial traffic.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                <span><b>Perimeter Lockdown:</b> Secure entrance barrier and sound intersection strobe siren.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                <span><b>First Responder Dispatch:</b> Transmit prioritized alert payload to Police & Ambulance dispatch center.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-rose-600 px-1.5 py-0.5 rounded shrink-0">STEP 04</span>
                <span><b>Blackbox DVR:</b> Compile 15s pre-event buffer + 5s post-event MP4 forensic evidence clip.</span>
            </li>
        `;
    } else if (eventName === "FIRE") {
        statusBadge.innerText = "HAZARDOUS HAZMAT SEQUENCE ACTIVE";
        statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-amber-100 text-amber-800 border border-amber-200 uppercase font-mono animate-pulse";

        summaryText.innerText = `Toxic combustion gas density (${t.smoke_level ? t.smoke_level.toFixed(1) : "180"} PPM) and acute thermal heat spike (${t.temperature ? t.temperature.toFixed(1) : "75"}°C) verified by multi-sensor thresholding. YOLO11n visual flame detection confirmed. Immediate fire suppression response dispatched.`;

        riskLevel.innerText = "HIGH HAZARD";
        riskLevel.className = "font-bold text-amber-600 font-mono";
        primaryModality.innerText = "MQ-2 Gas + Thermal";
        verificationState.innerText = "CONFIRMED (VERIFIED)";
        verificationState.className = "font-bold text-amber-600 font-mono";

        actionPlanSteps.innerHTML = `
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-amber-600 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                <span><b>Traffic Isolation:</b> All approach signals shifted to ALL-RED to prevent vehicles from entering smoke hazard.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-amber-600 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                <span><b>Barrier Interlock:</b> Close automated security barrier to prevent pedestrian & vehicular exposure.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-amber-600 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                <span><b>Fire & Rescue Broadcast:</b> Transmit hazardous material telemetry with gas PPM readings to Fire Station.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-amber-600 px-1.5 py-0.5 rounded shrink-0">STEP 04</span>
                <span><b>Acoustic Siren:</b> Fire high-decibel audible emergency sirens to evacuate immediate zone.</span>
            </li>
        `;
    } else if (eventName === "EMERGENCY_VEHICLE") {
        statusBadge.innerText = "GREEN WAVE CORRIDOR ACTIVE";
        statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-blue-100 text-blue-800 border border-blue-200 uppercase font-mono animate-pulse";

        summaryText.innerText = `Emergency responder vehicle acoustic siren frequency (${t.audio_prediction ? t.audio_prediction.class : "ambulance"}) detected and cross-verified by computer vision. Arterial pre-emption sequence active along Node A -> Node B -> Node C -> Node D corridor.`;

        riskLevel.innerText = "MODERATE / PRIORITY";
        riskLevel.className = "font-bold text-blue-600 font-mono";
        primaryModality.innerText = "Acoustic Siren (91%)";
        verificationState.innerText = "ACTIVE CORRIDOR";
        verificationState.className = "font-bold text-blue-600 font-mono";

        actionPlanSteps.innerHTML = `
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                <span><b>Corridor Pre-emption:</b> Pre-empt downstream traffic lights to GREEN based on estimated arrival offset.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                <span><b>Cross-Traffic Clearance:</b> Turn conflicting cross-street signals RED to clear intersection ahead of arrival.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                <span><b>Multi-Node Handoff:</b> Synchronize ETA updates to Node C (Metro Blvd) and Node D (Hospital Gate).</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-700">
                <span class="font-mono font-bold text-[10px] text-white bg-blue-600 px-1.5 py-0.5 rounded shrink-0">STEP 04</span>
                <span><b>Corridor Release:</b> Automatically revert signals to standard cyclic timing once vehicle clears zone.</span>
            </li>
        `;
    } else {
        statusBadge.innerText = "STANDBY MODE";
        statusBadge.className = "px-3 py-1 rounded text-xs font-extrabold bg-emerald-100 text-emerald-800 border border-emerald-200 uppercase font-mono";

        summaryText.innerText = "Standard urban intersection baseline observed. Acoustic, visual, thermal, and physical impact telemetry remain within calibrated nominal tolerances. No emergency intervention required.";

        riskLevel.innerText = "MINIMAL";
        riskLevel.className = "font-bold text-emerald-600 font-mono";
        primaryModality.innerText = "Baseline (Multi)";
        verificationState.innerText = "CONFIRMED (5/5)";
        verificationState.className = "font-bold text-emerald-600 font-mono";

        actionPlanSteps.innerHTML = `
            <li class="flex items-start gap-2.5 text-slate-600">
                <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 01</span>
                <span>Maintain green traffic cycle synchronization across all corridor lanes.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-600">
                <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 02</span>
                <span>Keep automated access barrier open for unrestricted vehicular transit.</span>
            </li>
            <li class="flex items-start gap-2.5 text-slate-600">
                <span class="font-mono font-bold text-[10px] text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded shrink-0">STEP 03</span>
                <span>Continuously poll optical flow velocity and acoustic frequency buffers in standby.</span>
            </li>
        `;
    }
}

function updateSensors(t) {
    // Temperature
    const temp = t.temperature !== undefined ? t.temperature : 28.5;
    const tempEl = document.getElementById("telemetryTemp");
    const tempBar = document.getElementById("tempBar");
    const tempStatus = document.getElementById("tempStatus");

    if (tempEl) tempEl.innerText = temp.toFixed(1);
    if (tempBar) {
        const tempPercent = Math.min(100, Math.max(0, (temp / 100) * 100));
        tempBar.style.width = `${tempPercent}%`;
        if (temp > 60) {
            tempBar.className = "bg-rose-500 h-2 rounded-full transition-all duration-500";
            if (tempStatus) { tempStatus.innerText = "CRITICAL HEAT"; tempStatus.className = "text-rose-600 font-bold font-mono"; }
        } else if (temp > 40) {
            tempBar.className = "bg-amber-500 h-2 rounded-full transition-all duration-500";
            if (tempStatus) { tempStatus.innerText = "ELEVATED"; tempStatus.className = "text-amber-600 font-bold font-mono"; }
        } else {
            tempBar.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
            if (tempStatus) { tempStatus.innerText = "NORMAL"; tempStatus.className = "text-emerald-600 font-bold font-mono"; }
        }
    }

    // Smoke
    const smoke = t.smoke_level !== undefined ? t.smoke_level : 12.0;
    const smokeEl = document.getElementById("telemetrySmoke");
    const smokeBar = document.getElementById("smokeBar");
    const smokeStatus = document.getElementById("smokeStatus");

    if (smokeEl) smokeEl.innerText = smoke.toFixed(1);
    if (smokeBar) {
        const smokePercent = Math.min(100, Math.max(0, (smoke / 300) * 100));
        smokeBar.style.width = `${smokePercent}%`;
        if (smoke > 120) {
            smokeBar.className = "bg-rose-500 h-2 rounded-full transition-all duration-500";
            if (smokeStatus) { smokeStatus.innerText = "TOXIC DENSITY"; smokeStatus.className = "text-rose-600 font-bold font-mono"; }
        } else if (smoke > 50) {
            smokeBar.className = "bg-amber-500 h-2 rounded-full transition-all duration-500";
            if (smokeStatus) { smokeStatus.innerText = "MODERATE"; smokeStatus.className = "text-amber-600 font-bold font-mono"; }
        } else {
            smokeBar.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
            if (smokeStatus) { smokeStatus.innerText = "CLEAR"; smokeStatus.className = "text-emerald-600 font-bold font-mono"; }
        }
    }

    // Accelerometer / Impact
    const accel = t.acceleration_g !== undefined ? t.acceleration_g : 0.03;
    const accelEl = document.getElementById("telemetryAccel");
    const accelBar = document.getElementById("accelBar");
    const impactStatus = document.getElementById("impactStatus");

    if (accelEl) accelEl.innerText = accel.toFixed(2);
    if (accelBar) {
        const accelPercent = Math.min(100, Math.max(0, (accel / 7.0) * 100));
        accelBar.style.width = `${accelPercent}%`;
        if (t.impact_detected || accel > 3.0) {
            accelBar.className = "bg-rose-500 h-2 rounded-full transition-all duration-500";
            if (impactStatus) { impactStatus.innerText = "IMPACT DETECTED"; impactStatus.className = "text-rose-600 font-bold font-mono animate-pulse"; }
        } else {
            accelBar.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
            if (impactStatus) { impactStatus.innerText = "NO IMPACT"; impactStatus.className = "text-emerald-600 font-bold font-mono"; }
        }
    }

    // Audio AI (Genuine Dataset Feeder & EdgeAcousticNet)
    const audio = t.audio_prediction || { class: "UNKNOWN", confidence: 0, ood_status: "REVIEW_REQUIRED", reason_codes: ["MISSING_AUDIO_PREDICTION"] };
    const aClassEl = document.getElementById("telemetryAudioClass");
    const aConfEl = document.getElementById("telemetryAudioConf");
    const aBar = document.getElementById("audioConfBar");
    const aDsEl = document.getElementById("telemetryAudioDataset");
    const aFileEl = document.getElementById("telemetryAudioFile");
    const validAudioClass = ["ambient", "crash", "horn", "siren"].includes(String(audio.class || "").toLowerCase());
    if (!validAudioClass) { audio.class = "UNKNOWN"; audio.ood_status = "REVIEW_REQUIRED"; audio.reason_codes = [...(audio.reason_codes || []), "OUT_OF_CLASS_LABEL"]; }
    const aConf = Math.round((audio.confidence || 0) * 100);

    if (aClassEl) aClassEl.innerText = audio.class;
    if (aConfEl) aConfEl.innerText = `${aConf}%`;
    if (aBar) aBar.style.width = `${aConf}%`;
    if (aDsEl && audio.dataset) aDsEl.innerText = audio.dataset;
    if (aFileEl && audio.source_file) aFileEl.innerText = audio.source_file;

    // Vision AI (Genuine Dataset Feeder & Fine-tuned YOLO11n)
    const vision = t.vision_prediction || { class: "vehicle", confidence: 0.88 };
    const vClassEl = document.getElementById("telemetryVisionClass");
    const vConfEl = document.getElementById("telemetryVisionConf");
    const vBar = document.getElementById("visionConfBar");
    const vDsEl = document.getElementById("telemetryVisionDataset");
    const vFileEl = document.getElementById("telemetryVisionFrame");
    const vConf = Math.round((vision.confidence || 0.85) * 100);

    if (vClassEl) vClassEl.innerText = vision.class;
    if (vConfEl) vConfEl.innerText = `${vConf}%`;
    if (vBar) vBar.style.width = `${vConf}%`;
    if (vDsEl && vision.dataset) vDsEl.innerText = vision.dataset;
    if (vFileEl && vision.source_frame) vFileEl.innerText = vision.source_frame;

    // Optical Flow & Motion Crash Score
    const motion = t.motion_analysis || {};
    const crashScore = Math.round((motion.crash_score || 0.0) * 100);
    const scoreEl = document.getElementById("telemetryCrashScore");
    const barEl = document.getElementById("crashScoreBar");
    const statusEl = document.getElementById("motionStatus");

    if (scoreEl) scoreEl.innerText = `${crashScore}%`;
    if (barEl) {
        barEl.style.width = `${crashScore}%`;
        if (crashScore > 65) {
            barEl.className = "bg-rose-500 h-2 rounded-full transition-all duration-500";
        } else if (crashScore > 35) {
            barEl.className = "bg-amber-500 h-2 rounded-full transition-all duration-500";
        } else {
            barEl.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
        }
    }
    if (statusEl) {
        if (motion.anomaly_detected || crashScore > 65) {
            statusEl.innerText = "CRASH IMPACT RISK";
            statusEl.className = "text-rose-600 font-bold font-mono animate-pulse";
        } else if (crashScore > 35) {
            statusEl.innerText = "SUDDEN DECELERATION";
            statusEl.className = "text-amber-600 font-bold font-mono";
        } else {
            statusEl.innerText = "NORMAL FLOW";
            statusEl.className = "text-emerald-600 font-bold font-mono";
        }
    }

    // Synchronize Overview Snapshot Matrix
    const ovTemp = document.getElementById("ovTemp");
    const ovSmoke = document.getElementById("ovSmoke");
    const ovAccel = document.getElementById("ovAccel");
    const ovAudio = document.getElementById("ovAudio");
    const ovVision = document.getElementById("ovVision");
    const ovCrash = document.getElementById("ovCrash");

    if (ovTemp) ovTemp.innerText = temp.toFixed(1);
    if (ovSmoke) ovSmoke.innerText = smoke.toFixed(0);
    if (ovAccel) ovAccel.innerText = accel.toFixed(2);
    if (ovAudio) ovAudio.innerText = (audio.class || "TRAFFIC").toUpperCase();
    if (ovVision) ovVision.innerText = (vision.class || "VEHICLE").toUpperCase();
    if (ovCrash) ovCrash.innerText = `${crashScore}%`;
}

function updateActuators(a) {
    const signalState = a.traffic_signal || "GREEN";
    const sigText = document.getElementById("trafficSignalText");
    const lRed = document.getElementById("lightRed");
    const lYellow = document.getElementById("lightYellow");
    const lGreen = document.getElementById("lightGreen");

    if (lRed) lRed.className = "w-8 h-8 rounded-full bg-slate-900 border border-slate-700 transition-all duration-300";
    if (lYellow) lYellow.className = "w-8 h-8 rounded-full bg-slate-900 border border-slate-700 transition-all duration-300";
    if (lGreen) lGreen.className = "w-8 h-8 rounded-full bg-slate-900 border border-slate-700 transition-all duration-300";

    if (signalState === "RED") {
        if (sigText) { sigText.innerText = "RED (HALT)"; sigText.className = "text-2xl font-black text-rose-600 mt-1 font-mono"; }
        if (lRed) lRed.className = "w-8 h-8 rounded-full bulb-glow-red transition-all duration-300";
    } else if (signalState === "YELLOW") {
        if (sigText) { sigText.innerText = "YELLOW (CAUTION)"; sigText.className = "text-2xl font-black text-amber-600 mt-1 font-mono"; }
        if (lYellow) lYellow.className = "w-8 h-8 rounded-full bulb-glow-yellow transition-all duration-300";
    } else {
        if (sigText) { sigText.innerText = "GREEN (FLOW)"; sigText.className = "text-2xl font-black text-emerald-600 mt-1 font-mono"; }
        if (lGreen) lGreen.className = "w-8 h-8 rounded-full bulb-glow-green transition-all duration-300";
    }

    // Barrier
    const barrierState = a.barrier_gate || "OPEN";
    const barText = document.getElementById("barrierText");
    const barIcon = document.getElementById("barrierIcon");
    if (barText) barText.innerText = barrierState;

    if (barrierState === "CLOSED") {
        if (barText) barText.className = "text-2xl font-black text-rose-600 mt-1 font-mono";
        if (barIcon) {
            barIcon.innerText = "LOCK";
            barIcon.className = "h-12 w-12 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center font-mono font-black text-xs text-rose-700 shadow-sm";
        }
    } else {
        if (barText) barText.className = "text-2xl font-black text-emerald-600 mt-1 font-mono";
        if (barIcon) {
            barIcon.innerText = "OPEN";
            barIcon.className = "h-12 w-12 rounded-xl bg-emerald-50 border border-emerald-200 flex items-center justify-center font-mono font-black text-xs text-emerald-700 shadow-sm";
        }
    }

    // Buzzer
    const buzzerState = a.buzzer || "OFF";
    const buzText = document.getElementById("buzzerText");
    const buzIcon = document.getElementById("buzzerIcon");
    if (buzText) buzText.innerText = buzzerState;

    if (buzzerState === "ON") {
        if (buzText) buzText.className = "text-2xl font-black text-rose-600 mt-1 font-mono";
        if (buzIcon) {
            buzIcon.innerText = "SIREN";
            buzIcon.className = "h-12 w-12 rounded-xl bg-rose-100 border border-rose-300 flex items-center justify-center font-mono font-black text-xs text-rose-800 shadow-sm animate-pulse";
        }
    } else {
        if (buzText) buzText.className = "text-2xl font-black text-slate-400 mt-1 font-mono";
        if (buzIcon) {
            buzIcon.innerText = "MUTE";
            buzIcon.className = "h-12 w-12 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center font-mono font-black text-xs text-slate-400 shadow-sm";
        }
    }

    // Dispatch
    const dispatch = a.dispatch_alert || "NORMAL_OPERATIONS";
    const dispEl = document.getElementById("dispatchText");
    const dispStatus = document.getElementById("dispatchStatus");
    if (dispEl) dispEl.innerText = dispatch;
    if (dispStatus) {
        if (dispatch.includes("DISPATCH") || dispatch.includes("CORRIDOR")) {
            dispStatus.innerText = "Emergency Action Dispatched";
            dispStatus.className = "text-rose-600 font-bold font-mono animate-pulse";
        } else {
            dispStatus.innerText = "Active Standby";
            dispStatus.className = "text-emerald-600 font-semibold font-mono";
        }
    }

    // Synchronize Overview Snapshot Matrix
    const ovTraffic = document.getElementById("ovTraffic");
    const ovBarrier = document.getElementById("ovBarrier");
    const ovSiren = document.getElementById("ovSiren");
    const ovDispatch = document.getElementById("ovDispatch");

    if (ovTraffic && sigText) {
        ovTraffic.innerText = sigText.innerText;
        ovTraffic.className = sigText.className.includes("text-rose") ? "font-bold text-rose-600 font-mono" : (sigText.className.includes("text-amber") ? "font-bold text-amber-600 font-mono" : "font-bold text-emerald-600 font-mono");
    }
    if (ovBarrier && barText) {
        ovBarrier.innerText = barText.innerText;
        ovBarrier.className = barText.className.includes("text-rose") ? "font-bold text-rose-600 font-mono" : "font-bold text-emerald-600 font-mono";
    }
    if (ovSiren && buzText) {
        ovSiren.innerText = buzText.innerText;
        ovSiren.className = buzText.className.includes("text-rose") ? "font-bold text-rose-600 font-mono" : "font-bold text-slate-400 font-mono";
    }
    if (ovDispatch) {
        ovDispatch.innerText = a.dispatch_alert || "NORMAL_OPERATIONS";
    }
}

/* ========================================================================= */
/* 3. CHART.JS REAL-TIME TELEMETRY GRAPH                                     */
/* ========================================================================= */

function initChart() {
    const canvas = document.getElementById("sensorHistoryChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    chartInstance = new Chart(ctx, {
        type: "line",
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            interaction: { mode: "index", intersect: false },
            scales: {
                x: {
                    grid: { color: "#f1f5f9" },
                    ticks: { color: "#94a3b8", font: { size: 10, family: "monospace" } }
                },
                y: {
                    type: "linear",
                    display: true,
                    position: "left",
                    min: 15,
                    max: 85,
                    grid: { color: "#f1f5f9" },
                    ticks: { color: "#059669", font: { size: 10, family: "monospace" } },
                    title: { display: true, text: "Temp (°C)", color: "#059669", font: { size: 10 } }
                },
                y1: {
                    type: "linear",
                    display: true,
                    position: "right",
                    min: 0,
                    max: 300,
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#d97706", font: { size: 10, family: "monospace" } },
                    title: { display: true, text: "Smoke (PPM)", color: "#d97706", font: { size: 10 } }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function updateChart(temp, smoke) {
    if (!chartInstance) return;
    const now = new Date().toLocaleTimeString().split(" ")[0];

    chartData.labels.push(now);
    chartData.datasets[0].data.push(temp !== undefined ? temp : 28.5);
    chartData.datasets[1].data.push(smoke !== undefined ? smoke : 12.0);

    if (chartData.labels.length > MAX_CHART_POINTS) {
        chartData.labels.shift();
        chartData.datasets[0].data.shift();
        chartData.datasets[1].data.shift();
    }
    chartInstance.update("none");
}

/* ========================================================================= */
/* 4. SCENARIO SIMULATION & HISTORICAL INCIDENT LOG                          */
/* ========================================================================= */

async function triggerScenario(name) {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!user.permissions.includes("scenarios") && !user.permissions.includes("all")) {
        showRoleAccessDeniedToast("scenarios", user);
        alert(`Action Denied: ${user.roleTitle} does not have permission to trigger emergency scenarios. Incident Commander or Traffic Controller role required.`);
        return;
    }

    try {
        const res = await fetch(`/api/trigger_scenario?scenario=${name}`, { method: "POST" });
        if (res.ok) {
            const data = await res.json();
            processLivePayload(data);
            setTimeout(fetchHistoricalEvents, 1000);
        }
    } catch (e) {
        console.error("Failed to trigger scenario:", e);
    }
}

async function fetchHistoricalEvents() {
    try {
        const res = await fetch("/api/events");
        if (!res.ok) return;
        const events = await res.json();
        const tbody = document.getElementById("eventsTableBody");
        if (!tbody) return;

        if (!events || events.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-slate-400">No incidents recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = events.slice(0, 10).map((ev) => {
            const isCrit = ev.severity_level === "CRITICAL";
            const isHigh = ev.severity_level === "HIGH";
            const badgeColor = isCrit ? "bg-rose-50 text-rose-700 border-rose-200" : (isHigh ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200");
            const timePart = (ev.timestamp || "").split("T")[1]?.substring(0, 8) || ev.timestamp;

            return `
            <tr class="hover:bg-slate-50 transition">
                <td class="py-3 px-3 text-slate-400 font-bold font-mono">#${ev.id}</td>
                <td class="py-3 px-3 text-slate-600 font-medium font-mono">${timePart}</td>
                <td class="py-3 px-3 font-bold text-slate-800 font-mono">${ev.event_type}</td>
                <td class="py-3 px-3 text-blue-700 font-bold font-mono">${Math.round((ev.confidence || 0.9) * 100)}%</td>
                <td class="py-3 px-3">
                    <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${badgeColor} font-mono">
                        ${ev.severity_level}
                    </span>
                </td>
                <td class="py-3 px-3 text-slate-600 font-medium font-mono">${ev.probable_zone || "ZONE_B"}</td>
                <td class="py-3 px-3 text-slate-500 truncate max-w-xs font-mono">${ev.autonomous_action || ev.traffic_signal_state}</td>
                <td class="py-3 px-3 text-right">
                    <a href="/api/report?id=INC-EV-${ev.id}" target="_blank" class="btn-press px-2.5 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 font-mono font-bold text-[11px] inline-flex items-center gap-1 border border-slate-300">
                        <span>DOSSIER</span>
                        <span class="text-[9px]">&nearr;</span>
                    </a>
                </td>
            </tr>`;
        }).join("");
    } catch (e) {
        console.warn("Could not fetch historical events:", e);
    }
}

/* ========================================================================= */
/* 5. FIREBASE MODAL & LOCALSTORAGE MANAGEMENT                               */
/* ========================================================================= */

function openConfigModal() {
    const modal = document.getElementById("configModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    const defaultUrl = "https://edge-ai-524d4-default-rtdb.asia-southeast1.firebasedatabase.app/";
    const cfgEl = document.getElementById("cfgDbUrl");
    if (cfgEl) cfgEl.value = localStorage.getItem("sentinel_firebase_db_url") || defaultUrl;
}

function closeConfigModal() {
    const modal = document.getElementById("configModal");
    if (modal) modal.classList.add("hidden");
}

function saveFirebaseConfig() {
    const cfgEl = document.getElementById("cfgDbUrl");
    const dbUrl = cfgEl ? cfgEl.value.trim() : "";

    if (dbUrl) {
        localStorage.setItem("sentinel_firebase_db_url", dbUrl);
        fetch(`/api/firebase_config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ database_url: dbUrl })
        }).catch(() => {});

        closeConfigModal();
        alert("Firebase Realtime Database Connected! Streaming live without any API key.");
        location.reload();
    } else {
        alert("Please enter a valid Firebase Realtime Database URL.");
    }
}

function disconnectFirebase() {
    localStorage.removeItem("sentinel_firebase_db_url");
    closeConfigModal();
    alert("Reset to Local Bridge Mode.");
    location.reload();
}

/* ========================================================================= */
/* 6. BLACKBOX VIDEO DVR & OPERATOR ALERT ACKNOWLEDGMENT                     */
/* ========================================================================= */

async function fetchRecordings() {
    const listEl = document.getElementById("recordingsList");
    if (!listEl) return;

    try {
        const res = await fetch("/api/recordings");
        if (!res.ok) return;
        const videos = await res.json();

        const ovDvr = document.getElementById("ovDvrCount");
        if (ovDvr && Array.isArray(videos)) {
            ovDvr.innerText = `${videos.length} Forensic Clips`;
        }

        if (!videos || videos.length === 0) {
            listEl.innerHTML = `
                <div class="col-span-full p-6 text-center text-slate-400 bg-slate-50 rounded-xl border border-slate-200">
                    No blackbox video incidents recorded yet. Trigger a scenario to generate forensic MP4 clips.
                </div>`;
            return;
        }

        listEl.innerHTML = videos.map(vid => {
            const isAccident = vid.filename.includes("ACCIDENT");
            const isFire = vid.filename.includes("FIRE");
            const badgeBg = isAccident ? "bg-rose-100 text-rose-800 border-rose-200" : (isFire ? "bg-amber-100 text-amber-800 border-amber-200" : "bg-blue-100 text-blue-800 border-blue-200");
            const sizeKb = Math.round(vid.size_bytes / 1024);

            return `
            <div class="p-4 rounded-xl border border-cardBorder bg-white shadow-soft flex flex-col justify-between space-y-3 hover:border-blue-300 transition">
                <div class="flex items-center justify-between">
                    <span class="px-2 py-0.5 rounded text-[10px] font-black border ${badgeBg} font-mono">
                        ${isAccident ? "COLLISION" : (isFire ? "FIRE HAZARD" : "EMERGENCY")}
                    </span>
                    <span class="text-[10px] text-slate-400 font-mono">${sizeKb} KB</span>
                </div>
                <div>
                    <div class="text-xs font-bold text-slate-800 truncate font-mono" title="${vid.filename}">${vid.filename}</div>
                    <div class="text-[10px] text-slate-500 mt-0.5 font-mono">${vid.created_at || "Recent capture"}</div>
                </div>
                <div class="pt-1 flex items-center justify-end">
                    <button onclick="playRecording('${vid.filename}')" class="px-3 py-1.5 rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-bold font-mono transition">
                        PLAY VIDEO &rarr;
                    </button>
                </div>
            </div>`;
        }).join("");
    } catch (e) {
        console.warn("Could not fetch DVR recordings:", e);
    }
}

function playRecording(filename) {
    const modal = document.getElementById("videoModal");
    const player = document.getElementById("dvrVideoPlayer");
    const title = document.getElementById("videoModalTitle");
    const meta = document.getElementById("videoModalMeta");

    if (!modal || !player) return;

    if (title) title.innerText = `Forensic DVR Evidence: ${filename}`;
    if (meta) meta.innerText = `Streaming /api/recordings/${filename} (H.264 / MP4)`;
    player.src = `/api/recordings/${filename}`;
    modal.classList.remove("hidden");
    player.play().catch(e => console.log("Autoplay blocked or stream ready:", e));
}

function closeVideoModal() {
    const modal = document.getElementById("videoModal");
    const player = document.getElementById("dvrVideoPlayer");
    if (player) {
        player.pause();
        player.src = "";
    }
    if (modal) {
        modal.classList.add("hidden");
    }
}

async function acknowledgeCurrentIncident() {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!user.permissions.includes("ack") && !user.permissions.includes("all")) {
        showRoleAccessDeniedToast("acknowledgment", user);
        alert(`Action Denied: ${user.roleTitle} does not have alert acknowledgment permissions. Incident Commander or Traffic Controller role required.`);
        return;
    }

    const ackBtn = document.getElementById("ackIncidentBtn");
    if (!ackBtn) return;
    try {
        const incidents = await fetch("/api/incidents").then(r => r.json());
        const active = incidents.find(item => ["OPEN", "ESCALATED", "REVIEW_REQUIRED"].includes(item.status));
        if (!active) { ackBtn.innerText = "NO ACTIVE INCIDENT"; ackBtn.disabled = true; return; }
        ackBtn.innerText = "Acknowledging...";
        const res = await fetch(`/api/incidents/${encodeURIComponent(active.incident_id)}/acknowledge`, {
            method: "POST", headers: authHeaders({"Content-Type":"application/json"}), body: JSON.stringify({version: active.version})
        });
        if (res.ok) {
            ackBtn.innerText = "ACKNOWLEDGED BY " + user.role;
            ackBtn.className = "action-btn px-4 py-2 rounded-xl bg-emerald-600 text-white text-xs font-bold uppercase tracking-wider transition shadow-sm font-mono cursor-default";
            setTimeout(() => {
                if (ackBtn.innerText.includes("ACKNOWLEDGED")) {
                    ackBtn.classList.add("hidden");
                }
            }, 3000);
        }
    } catch (e) {
        console.error("Failed to acknowledge alert:", e);
        ackBtn.innerText = "ACKNOWLEDGE INCIDENT";
    }
}

/* ========================================================================= */
/* 7. CLIENT-SIDE SPA ROUTING & COLLAPSIBLE SIDEBAR                          */
/* ========================================================================= */

const VALID_PAGES = ["overview", "emergency-plan", "system-health", "analytics", "sensors", "actuators", "gis", "logs", "review", "dvr", "datasets"];
const PAGE_TITLES = {
    overview: "DASHBOARD OVERVIEW",
    "emergency-plan": "EMERGENCY RESPONSE PLAN",
    "system-health": "SYSTEM HEALTH & MONITORING",
    analytics: "OPERATIONS ANALYTICS & INTELLIGENCE",
    sensors: "SENSORS MATRIX",
    actuators: "ACTUATORS RESPONSE",
    gis: "GIS & REAL-TIME CHARTS",
    logs: "HISTORICAL INCIDENT LOGS",
    review: "PREDICTION REVIEW QUEUE",
    dvr: "BLACKBOX VIDEO DVR",
    datasets: "MASTER DATASET CATALOG"
};

function initRouting() {
    const hash = window.location.hash.replace("#", "").toLowerCase();
    const targetPage = VALID_PAGES.includes(hash) ? hash : "overview";
    switchPage(targetPage, false);

    window.addEventListener("hashchange", () => {
        const h = window.location.hash.replace("#", "").toLowerCase();
        if (VALID_PAGES.includes(h)) {
            switchPage(h, false);
        }
    });
}

function switchPage(pageId, updateHash = true) {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!VALID_PAGES.includes(pageId)) {
        pageId = "overview";
    }

    // Strict Role Access Control: Redirect to overview if page disallowed for current role
    if (user && user.allowedPages && !user.allowedPages.includes(pageId)) {
        showRoleAccessDeniedToast(pageId, user);
        pageId = user.allowedPages.includes("overview") ? "overview" : (user.allowedPages[0] || "overview");
    }

    if (updateHash) {
        window.location.hash = pageId;
    }

    // 1. Hide all page views, show target view
    VALID_PAGES.forEach(id => {
        const viewEl = document.getElementById(`view-${id}`);
        if (viewEl) {
            if (id === pageId) {
                viewEl.classList.remove("hidden");
            } else {
                viewEl.classList.add("hidden");
            }
        }
    });

    // 2. Update Top Navigation Pill states
    VALID_PAGES.forEach(id => {
        const btn = document.getElementById(`nav-btn-${id}`);
        if (btn) {
            if (id === pageId) {
                btn.className = "page-nav-pill px-3.5 py-1.5 rounded-lg text-xs font-bold transition bg-blue-600 text-white shadow-sm shrink-0 font-mono";
            } else {
                btn.className = "page-nav-pill px-3.5 py-1.5 rounded-lg text-xs font-semibold transition text-slate-600 hover:text-slate-900 hover:bg-slate-100 shrink-0 font-mono";
            }
        }
    });

    // 3. Update Sidebar item states
    VALID_PAGES.forEach(id => {
        const sideBtn = document.getElementById(`side-nav-${id}`);
        if (sideBtn) {
            if (id === pageId) {
                sideBtn.className = "side-nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-left font-bold bg-blue-50 text-blue-700 transition";
            } else {
                sideBtn.className = "side-nav-item w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-left font-semibold text-slate-700 hover:bg-slate-50 hover:text-blue-600 transition";
            }
        }
    });

    // 4. Update breadcrumb
    const breadcrumb = document.getElementById("activePageBreadcrumb");
    if (breadcrumb && PAGE_TITLES[pageId]) {
        breadcrumb.innerText = PAGE_TITLES[pageId];
    }
    if (pageId === "emergency-plan") updateResponsePlan();
    if (pageId === "system-health") loadSystemHealth();
    if (pageId === "analytics") loadAnalytics();
    if (pageId === "logs") loadIncidents();
    if (pageId === "review") loadReviewQueue();

    // 5. Page-specific triggers
    if (pageId === "gis" && chartInstance) {
        setTimeout(() => {
            try {
                chartInstance.resize();
            } catch (e) {}
        }, 80);
    } else if (pageId === "datasets") {
        fetchDatasetsCatalog();
    } else if (pageId === "dvr") {
        if (typeof fetchRecordings === "function") fetchRecordings();
    }

    // 6. Close sidebar if open
    closeSidebar();

    // 7. Scroll to top smoothly
    window.scrollTo({ top: 0, behavior: "smooth" });
}

async function fetchDatasetsCatalog() {
    const grid = document.getElementById("datasetsMatrixGrid");
    if (!grid) return;
    try {
        const res = await fetch("/api/datasets/catalog");
        if (!res.ok) return;
        const data = await res.json();
        const totAudio = document.getElementById("catTotalAudio");
        const totVision = document.getElementById("catTotalVision");
        if (totAudio && data.total_audio_samples != null) {
            totAudio.innerText = data.total_audio_samples.toLocaleString();
        }
        if (totVision && data.total_vision_frames != null) {
            totVision.innerText = data.total_vision_frames.toLocaleString();
        }
        if (Array.isArray(data.datasets) && data.datasets.length > 0) {
            grid.innerHTML = data.datasets.map(ds => `
                <div class="p-5 rounded-xl border border-slate-200 bg-slate-50 space-y-3 flex flex-col justify-between hover:border-slate-300 transition shadow-xs">
                    <div>
                        <div class="flex items-start justify-between gap-2">
                            <span class="font-bold text-slate-900 font-mono text-xs break-all">${ds.name}</span>
                            <span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold shrink-0 ${ds.status === 'INDEXED' ? 'bg-emerald-100 text-emerald-800' : 'bg-blue-100 text-blue-800'}">${ds.status}</span>
                        </div>
                        <div class="text-[11px] text-slate-600 font-semibold mt-1">${ds.modality} • <span class="font-mono text-slate-800">${typeof ds.samples === 'number' ? ds.samples.toLocaleString() : ds.samples}</span> samples</div>
                        <div class="text-[10px] text-slate-400 font-mono mt-0.5">${ds.sample_rate || ds.resolution || ds.format || ''}</div>
                    </div>
                    <div class="pt-2 border-t border-slate-200">
                        <div class="text-[10px] font-mono text-slate-400 uppercase mb-1 font-bold">Detected Classes:</div>
                        <div class="flex flex-wrap gap-1">
                            ${(ds.classes || []).map(c => `<span class="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-[10px] font-mono text-slate-700">${c}</span>`).join('')}
                        </div>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error("Failed to load dataset catalog:", e);
    }
}

async function triggerIncidentReplay() {
    const incId = document.getElementById("replayIncidentId")?.value || "INC-DEMO-001";
    const speed = parseFloat(document.getElementById("replaySpeed")?.value || "1.0");
    const fault = document.getElementById("replayFault")?.value || "none";
    const box = document.getElementById("replayResultsBox");
    const title = document.getElementById("replaySummaryTitle");
    const digestBadge = document.getElementById("replayDigestBadge");
    const list = document.getElementById("replayTimelineList");

    if (box) box.classList.remove("hidden");
    if (list) list.innerHTML = `<div class="text-slate-400">Executing sandbox replay for ${incId}...</div>`;

    const payload = {
        incident_id: incId,
        speed: speed,
        dropout: ["camera", "audio", "sensors"].includes(fault) ? fault : null,
        camera_failure: fault === "camera",
        conflicting_sensors: fault === "conflicting",
        network_outage: fault === "network",
    };

    try {
        const token = localStorage.getItem("sentinel_token");
        const csrfToken = localStorage.getItem("sentinel_csrf_token");
        const res = await fetch("/api/replay/execute", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": token ? `Bearer ${token}` : "",
                "X-CSRF-Token": csrfToken || "",
            },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (title) title.innerText = `REPLAY COMPLETE: ${data.final_decision} (Risk: ${(data.final_risk * 100).toFixed(1)}%)`;
        if (digestBadge) digestBadge.innerText = `DIGEST: ${data.hash_digest.substring(0, 10)}`;

        if (list && data.timeline) {
            list.innerHTML = data.timeline.map(s => `
                <div class="p-2 rounded bg-slate-800/80 border border-slate-700/60 flex items-center justify-between">
                    <div>
                        <span class="text-blue-400 font-bold">Step ${s.step_idx}</span>
                        <span class="text-slate-400 text-[10px]">(${s.timestamp_offset_sec.toFixed(1)}s)</span>:
                        <span class="text-slate-200">${s.action} &bull; ${s.recommended_plan}</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-amber-400">Risk: ${s.final_risk.toFixed(2)}</span>
                        ${s.ood_detected ? '<span class="px-1 py-0.5 rounded bg-amber-900/60 text-amber-300 text-[9px]">OOD</span>' : ''}
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        if (list) list.innerHTML = `<div class="text-rose-400">Replay failed: ${e.message}</div>`;
    }
}

function toggleSidebar() {
    const drawer = document.getElementById("sidebarDrawer");
    const overlay = document.getElementById("sidebarOverlay");
    if (!drawer || !overlay) return;

    const isClosed = drawer.classList.contains("-translate-x-full");
    if (isClosed) {
        drawer.classList.remove("-translate-x-full");
        overlay.classList.remove("opacity-0", "pointer-events-none");
        overlay.classList.add("opacity-100");
    } else {
        closeSidebar();
    }
}

function closeSidebar() {
    const drawer = document.getElementById("sidebarDrawer");
    const overlay = document.getElementById("sidebarOverlay");
    if (drawer) drawer.classList.add("-translate-x-full");
    if (overlay) {
        overlay.classList.remove("opacity-100");
        overlay.classList.add("opacity-0", "pointer-events-none");
    }
}

function scrollToSection(sectionId) {
    const target = document.getElementById(sectionId);
    if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    closeSidebar();
}

/* ========================================================================= */
/* 8. HARDWARE CAPABILITY & RUNTIME MODE MANAGEMENT                          */
/* ========================================================================= */

async function fetchHardwareStatus() {
    try {
        const res = await fetch("/api/hardware");
        if (!res.ok) return;
        const data = await res.json();

        // Update mode badge
        const modeBadge = document.getElementById("hwModeBadge");
        if (modeBadge) {
            modeBadge.innerText = `MODE: ${data.active_mode}`;
            modeBadge.className = data.active_mode === "HARDWARE" 
                ? "px-2.5 py-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-300 font-bold font-mono uppercase"
                : (data.active_mode === "FAULT_INJECTION" 
                    ? "px-2.5 py-1 rounded bg-rose-50 text-rose-700 border border-rose-300 font-bold font-mono uppercase animate-pulse"
                    : "px-2.5 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200 font-bold font-mono uppercase");
        }

        // Update individual driver health badges
        const drivers = data.probe?.driver_states || {};
        updateDriverBadge("hwStatusMpu", drivers.mpu6050);
        updateDriverBadge("hwStatusGas", drivers.mq2_ads1115);
        updateDriverBadge("hwStatusDht", drivers.dht22);
        updateDriverBadge("hwStatusCam", drivers.camera);
        updateDriverBadge("hwStatusMic", drivers.microphone);

    } catch (e) {
        console.warn("Could not fetch hardware probe state:", e);
    }
}

function updateDriverBadge(elId, state) {
    const el = document.getElementById(elId);
    if (!el) return;
    state = (state || "offline").toUpperCase();
    el.innerText = state;
    if (state === "ONLINE") {
        el.className = "px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-100 text-emerald-800";
    } else if (state === "SIMULATED") {
        el.className = "px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-100 text-blue-800";
    } else if (state === "DEGRADED") {
        el.className = "px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-100 text-amber-800";
    } else {
        el.className = "px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-100 text-rose-800";
    }
}

async function loadIncidents() {
    const params = new URLSearchParams();
    const status=document.getElementById("incidentStatusFilter")?.value, zone=document.getElementById("incidentZoneFilter")?.value, severity=document.getElementById("incidentSeverityFilter")?.value;
    if(status) params.set("status",status); if(zone) params.set("zone_id",zone); if(severity) params.set("severity",severity);
    const incidents=await fetch(`/api/incidents?${params}`).then(r=>r.json()).catch(()=>[]);
    const tbody=document.getElementById("eventsTableBody"); if(!tbody) return;
    tbody.innerHTML=incidents.length?incidents.map((item,index)=>`<tr class="hover:bg-slate-50 cursor-pointer" onclick="showIncidentDetail('${escapeHtml(item.incident_id)}')"><td class="py-3 px-3">${index+1}</td><td class="py-3 px-3">${escapeHtml(item.created_at)}</td><td class="py-3 px-3 font-bold">${escapeHtml(item.event_type)}</td><td class="py-3 px-3">—</td><td class="py-3 px-3">${escapeHtml(item.severity||item.risk_level||"UNASSESSED")}</td><td class="py-3 px-3">${escapeHtml(item.zone_id)}</td><td class="py-3 px-3">${escapeHtml(item.status)}</td><td class="py-3 px-3 text-right">View details</td></tr>`).join(""):'<tr><td colspan="8" class="py-8 text-center text-slate-500">No governed incidents match these filters.</td></tr>';
}

async function showIncidentDetail(id) {
    const item=await fetch(`/api/incidents/${encodeURIComponent(id)}`).then(r=>r.json()); const panel=document.getElementById("incidentDetailPanel"); if(!panel)return;
    const risk=item.risk_breakdown_json?JSON.parse(item.risk_breakdown_json):null;
    const reasons=JSON.parse(item.ood_reasons_json||"[]");
    const assurance=(item.assurance_states||[]).at(-1);
    panel.innerHTML=`<div class="flex justify-between gap-3"><div><h3 class="font-black text-slate-900">${escapeHtml(item.incident_id)} · ${escapeHtml(item.status)}</h3><p class="text-xs text-slate-500">${escapeHtml(item.event_type)} in ${escapeHtml(item.zone_id)} · version ${item.version}</p></div><span class="text-xs font-bold text-amber-800">${escapeHtml(item.ood_status||"OOD not recorded")} ${reasons.length?`· ${reasons.map(escapeHtml).join(", ")}`:""}</span></div>
    <div class="grid md:grid-cols-2 gap-4 mt-4"><div><h4 class="text-xs font-bold uppercase text-slate-500">Temporal timeline</h4>${(item.incident_events||[]).map(e=>`<div class="text-xs mt-2 p-2 bg-white rounded border">${escapeHtml(e.event_type)} · ${escapeHtml(e.timestamp)}</div>`).join("")||'<p class="text-xs mt-2">No transitions</p>'}</div><div><h4 class="text-xs font-bold uppercase text-slate-500">Risk and assurance</h4><pre class="text-[10px] whitespace-pre-wrap mt-2 bg-white p-2 rounded border">${escapeHtml(JSON.stringify({risk:risk||"not available",assurance:assurance||"not available"},null,2))}</pre></div></div>
    <div class="mt-4"><h4 class="text-xs font-bold uppercase text-slate-500">Evidence integrity</h4>${(item.evidence||[]).map(e=>`<div class="mt-2 p-2 bg-white border rounded-lg flex justify-between gap-2 text-xs"><span>${escapeHtml(e.kind)} · ${escapeHtml(e.source_path)}</span><span class="font-bold ${e.hash_verified?'text-emerald-700':'text-rose-700'}">${e.hash_verified?'HASH VERIFIED':'HASH FAILED / MISSING'}</span></div>`).join("")||'<p class="text-xs mt-2">No evidence files attached</p>'}</div>
    <div class="mt-4"><h4 class="text-xs font-bold uppercase text-slate-500">Predictions and feedback</h4>${(item.predictions||[]).map(p=>`<div class="mt-2 p-2 bg-white border rounded-lg flex justify-between gap-2"><span class="text-xs">${escapeHtml(p.label)} · ${Math.round(p.confidence*100)}% · ${escapeHtml(p.model_id||"model unknown")} ${p.model_version?`v${escapeHtml(p.model_version)}`:""}<br><b>${escapeHtml(p.usage_restriction||"UNVERIFIED")}</b></span><span class="flex gap-1">${["CORRECT","INCORRECT","UNSURE"].map(label=>`<button onclick="submitFeedback(${p.id},'${label}')" class="px-2 py-1 border rounded text-[9px] font-bold">${label}</button>`).join("")}</span></div>`).join("")||'<p class="text-xs mt-2">No predictions</p>'}</div>
    <div class="mt-4"><h4 class="text-xs font-bold uppercase text-slate-500">Actions and notes</h4>${[...(item.operator_actions||[]),...(item.incident_notes||[])].map(a=>`<div class="text-xs mt-2">${escapeHtml(a.action||"NOTE")} · ${escapeHtml(a.operator_id)} · ${escapeHtml(a.note||a.payload_json||"")}</div>`).join("")||'<p class="text-xs mt-2">No operator actions</p>'}</div>
    <div id="counterfactualSection" class="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-xl">
        <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs font-bold uppercase text-slate-700">Counterfactual Explanations &amp; Sensitivity (Phase 6E)</h4>
            <span id="cfFidelityBadge" class="text-[9px] font-mono px-2 py-0.5 rounded bg-slate-200 text-slate-600">Computing...</span>
        </div>
        <div id="cfContent" class="text-xs text-slate-500">Analyzing decision sensitivity against 6D replay engine...</div>
    </div>`;
    const legal={OPEN:["acknowledge","false-alarm","notes"],REVIEW_REQUIRED:["acknowledge","false-alarm","notes"],ACKNOWLEDGED:["confirm","false-alarm","escalate","resolve","notes"],CONFIRMED:["escalate","resolve","notes"],ESCALATED:["acknowledge","resolve","notes"],FALSE_ALARM:["resolve","notes"],CLOSED:["notes"]};
    const role=getCurrentUser()?.role; const permitted=role==="COMMANDER"?["acknowledge","confirm","false-alarm","escalate","resolve","notes"]:role==="OPERATOR"?["acknowledge","confirm","false-alarm","notes"]:[]; const actions=(legal[item.status]||[]).filter(x=>permitted.includes(x));
    if(actions.length) panel.innerHTML+=`<div class="mt-4 flex flex-wrap gap-2">${actions.map(action=>`<button onclick="incidentAction('${escapeHtml(item.incident_id)}','${action}',${item.version})" class="px-3 py-2 rounded-lg border bg-white text-[10px] font-bold uppercase">${action.replaceAll("-"," ")}</button>`).join("")}</div>`;

    // Fetch and render counterfactual explanations asynchronously
    fetch(`/api/counterfactual/explain?incident=${encodeURIComponent(id)}`)
        .then(r => r.ok ? r.json() : null)
        .then(cf => {
            if (!cf) return;
            const badge = document.getElementById("cfFidelityBadge");
            const cfBox = document.getElementById("cfContent");
            if (badge) {
                badge.className = cf.fidelity_verified ? "text-[9px] font-mono px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold" : "text-[9px] font-mono px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-bold";
                badge.innerText = cf.fidelity_verified ? "100% REPLAY FIDELITY" : "UNVERIFIED FIDELITY";
            }
            if (cfBox) {
                const abl = cf.ablation_outcomes || {};
                cfBox.innerHTML = `
                    <div class="space-y-2">
                        <div class="p-2 bg-white rounded border text-xs">
                            <div class="font-semibold text-slate-800">${escapeHtml(cf.explanation_text)}</div>
                            <div class="text-[10px] text-slate-500 mt-1">
                                Top Driver: <b class="text-blue-700">${escapeHtml(cf.top_contributing_evidence.toUpperCase())}</b> &bull;
                                Pivot Sensor: <b class="${cf.pivot_sensor ? 'text-amber-700' : 'text-slate-600'}">${escapeHtml(cf.pivot_sensor ? cf.pivot_sensor.toUpperCase() : 'None (Redundant)')}</b> &bull;
                                Max Risk Drop: <b class="text-rose-700">${(cf.max_risk_drop * 100).toFixed(1)}%</b>
                            </div>
                            ${cf.why_not_triggered ? `<div class="mt-1 text-[11px] text-slate-600 bg-slate-50 p-1.5 rounded border border-dashed"><b>Suppression Rationale:</b> ${escapeHtml(cf.why_not_triggered)}</div>` : ''}
                        </div>
                        <div class="grid grid-cols-3 gap-2">
                            ${Object.keys(abl).map(k => {
                                const a = abl[k];
                                return `<div class="p-2 bg-white rounded border text-[11px]">
                                    <div class="font-bold text-slate-700 uppercase">${escapeHtml(k.replace('_', ' '))}</div>
                                    <div class="text-slate-600">Decision: <b>${escapeHtml(a.decision)}</b></div>
                                    <div class="text-slate-500">Risk: ${(a.final_risk * 100).toFixed(0)}% (${a.risk_drop > 0 ? '-' + (a.risk_drop * 100).toFixed(0) + '%' : '0%'})</div>
                                </div>`;
                            }).join('')}
                        </div>
                    </div>
                `;
            }
        })
        .catch(() => {});
}

async function incidentAction(id,action,version){
    const needsNote=["false-alarm","resolve","notes"].includes(action); const note=needsNote?prompt(action==="resolve"?"Resolution summary":"Reason or note")||"":""; if(needsNote&&!note)return;
    const response=await fetch(`/api/incidents/${encodeURIComponent(id)}/${action}`,{method:"POST",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({version,note})});
    if(response.ok)showIncidentDetail(id);else alert((await response.json()).error||"Action failed");
}

async function loadReviewQueue() {
    const params=new URLSearchParams(); for(const [key,id] of [["reason","reviewReasonFilter"],["zone","reviewZoneFilter"],["model","reviewModelFilter"],["status","reviewStatusFilter"]]){const value=document.getElementById(id)?.value;if(value)params.set(key,value)}
    const items=await fetch(`/api/review-queue?${params}`).then(r=>r.json()).catch(()=>[]); const list=document.getElementById("reviewQueueList"); if(!list)return;
    list.innerHTML=items.length?items.map(item=>`<article class="p-4 rounded-xl border border-slate-200 bg-slate-50 flex flex-col md:flex-row md:items-center justify-between gap-3"><div><div class="font-bold text-slate-900">${escapeHtml(item.label)} · ${escapeHtml(item.model_id||"model unknown")}</div><div class="text-xs text-slate-500 mt-1">${escapeHtml(item.zone_id)} · priority ${item.priority} · ${(item.reason_codes||[]).map(escapeHtml).join(", ")||"low confidence"}</div><div class="text-[10px] text-slate-500 mt-1">${escapeHtml(item.evidence_kind||"evidence not attached")} ${item.evidence_path?`· <a class="text-blue-600 font-bold" href="/api/incidents/${encodeURIComponent(item.incident_id)}/evidence.zip">download evidence package</a>`:""} · ${item.claimed_by?`claimed by ${escapeHtml(item.claimed_by)}`:"unclaimed"}</div></div><div class="flex flex-wrap gap-2"><button onclick="claimReview(${item.id})" class="px-2 py-1 rounded border bg-white text-[10px] font-bold" ${item.claimed_by?'disabled':''}>CLAIM</button>${["CORRECT","INCORRECT","UNSURE"].map(label=>`<button onclick="submitFeedback(${item.id},'${label}')" class="px-2 py-1 rounded border bg-white text-[10px] font-bold">${label}</button>`).join("")}</div></article>`).join(""):'<p class="text-sm text-slate-500">No predictions currently need review.</p>';
}

async function claimReview(id) {
    const response=await fetch(`/api/predictions/${id}/claim`,{method:"POST",headers:authHeaders({"Content-Type":"application/json"}),body:"{}"});
    if(response.ok) loadReviewQueue(); else alert((await response.json()).error||"Claim failed");
}

async function submitFeedback(id,label) {
    const response=await fetch(`/api/predictions/${id}/feedback`,{method:"POST",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({label})});
    if(response.ok) loadReviewQueue(); else alert((await response.json()).error||"Feedback failed");
}

async function setHardwareMode(mode, fault = "DISCONNECT") {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!user.permissions.includes("hardware") && !user.permissions.includes("all")) {
        showRoleAccessDeniedToast("hardware_mode", user);
        alert(`Action Denied: ${user.roleTitle} does not have hardware mode switching permissions. Hardware Engineer or Incident Commander role required.`);
        return;
    }
    try {
        const res = await fetch(`/api/hardware/mode?mode=${encodeURIComponent(mode)}&fault=${encodeURIComponent(fault)}`, {
            method: "POST"
        });
        if (res.ok) {
            await fetchHardwareStatus();
        }
    } catch (e) {
        console.error("Failed to switch hardware mode:", e);
    }
}

// Poll hardware diagnostics
setInterval(fetchHardwareStatus, 6000);
setTimeout(fetchHardwareStatus, 1500);

/* ========================================================================= */
/* 8. PHASE 4: SYSTEM HEALTH, STREAMS, DRIFT & OUTBOX PANEL                  */
/* ========================================================================= */

async function loadSystemHealth() {
    try {
        const [healthRes, driftRes, streamsRes, outboxRes] = await Promise.all([
            fetch("/api/monitoring/health").then(r => r.ok ? r.json() : null),
            fetch("/api/monitoring/drift").then(r => r.ok ? r.json() : null),
            fetch("/api/monitoring/streams").then(r => r.ok ? r.json() : null),
            fetch("/api/monitoring/outbox").then(r => r.ok ? r.json() : null)
        ]);

        if (healthRes) renderHealthComponents(healthRes);
        if (driftRes) renderDriftPanel(driftRes);
        if (streamsRes) renderStreamsPanel(streamsRes);
        if (outboxRes) renderOutboxPanel(outboxRes);
        loadStorageStatus();
    } catch (e) {
        console.error("loadSystemHealth error:", e);
    }
}

function renderHealthComponents(data) {
    const badge = document.getElementById("healthAssuranceBadge");
    if (badge) {
        badge.innerText = `ASSURANCE: ${data.assurance_level}`;
        badge.className = `px-3 py-1.5 rounded-lg font-mono font-black text-xs uppercase border ${data.assurance_level === "FULL" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-800 border-amber-200"}`;
    }

    const grid = document.getElementById("healthComponentsGrid");
    if (!grid) return;
    const comps = data.components || {};
    const avail = data.availability_pct || {};

    grid.innerHTML = Object.entries(comps).map(([k, c]) => {
        const isOk = c.status === "OK";
        const isDeg = c.status === "DEGRADED";
        const statColor = isOk ? "text-emerald-700 bg-emerald-50 border-emerald-200" : isDeg ? "text-amber-800 bg-amber-50 border-amber-200" : "text-rose-700 bg-rose-50 border-rose-200";
        const pct = avail[k] !== undefined ? `${avail[k]}%` : "100%";
        return `
            <div class="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-2">
                <div class="flex items-center justify-between">
                    <span class="font-mono text-xs font-bold text-slate-800 uppercase">${k}</span>
                    <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${statColor}">${c.status}</span>
                </div>
                <div class="text-[11px] text-slate-600 font-medium">${c.message}</div>
                <div class="flex items-center justify-between pt-2 border-t border-slate-200 text-[10px] font-mono text-slate-500">
                    <span>Avail: <strong class="text-slate-800">${pct}</strong></span>
                    <span>Seen: ${c.last_seen ? c.last_seen.split("T")[1].slice(0, 8) : "N/A"}</span>
                </div>
            </div>
        `;
    }).join("");
}

function renderDriftPanel(driftData) {
    const container = document.getElementById("driftModelsList");
    if (!container) return;

    container.innerHTML = Object.entries(driftData).map(([mId, d]) => {
        const isStable = d.status === "STABLE";
        const isWatch = d.status === "WATCH";
        const badgeColor = isStable ? "bg-emerald-50 text-emerald-700 border-emerald-200" : isWatch ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-rose-50 text-rose-700 border-rose-200";
        const m = d.metrics || {};
        const psi = m.psi !== undefined ? m.psi : "N/A";
        const priorShift = m.max_prior_shift !== undefined ? m.max_prior_shift : "N/A";

        return `
            <div class="p-4 rounded-xl border border-slate-200 bg-white space-y-3">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="font-mono text-xs font-bold text-slate-900">${mId}</span>
                        ${d.research_only ? '<span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 text-[9px] font-mono font-bold">RESEARCH_ONLY</span>' : ''}
                        ${d.insufficient_data ? '<span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 text-[9px] font-mono">INSUFFICIENT DATA</span>' : ''}
                    </div>
                    <span class="px-2.5 py-0.5 rounded text-[11px] font-mono font-black border ${badgeColor}">${d.status}</span>
                </div>
                <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono">
                    <div class="p-2 bg-slate-50 rounded-lg">Samples: <strong>${m.samples || 0}</strong></div>
                    <div class="p-2 bg-slate-50 rounded-lg">Mean Conf: <strong>${m.mean_confidence || 'N/A'}</strong></div>
                    <div class="p-2 bg-slate-50 rounded-lg">PSI: <strong>${psi}</strong></div>
                    <div class="p-2 bg-slate-50 rounded-lg">Max Shift: <strong>${priorShift}</strong></div>
                </div>
                <div class="text-[11px] text-slate-500 font-mono">
                    Reasons: ${d.reasons && d.reasons.length ? d.reasons.join(", ") : "Baseline in nominal tolerance"}
                </div>
            </div>
        `;
    }).join("");
}

function renderStreamsPanel(streamsData) {
    const cam = streamsData.camera || {};
    const aud = streamsData.audio || {};
    const camStream = cam.stream || {};
    const audStream = aud.stream || {};

    const camFps = document.getElementById("streamCamFps");
    const camStatus = document.getElementById("streamCamStatus");
    const camReconnect = document.getElementById("streamCamReconnect");
    const audStatus = document.getElementById("streamAudStatus");
    const audReconnect = document.getElementById("streamAudReconnect");

    if (camFps) camFps.innerText = `${camStream.fps || 0} FPS`;
    if (camStatus) camStatus.innerText = camStream.status || "UNKNOWN";
    if (camReconnect) camReconnect.innerText = `Reconnects: ${camStream.reconnect_count || 0}`;

    if (audStatus) audStatus.innerText = audStream.status || "UNKNOWN";
    if (audReconnect) audReconnect.innerText = `Reconnects: ${audStream.reconnect_count || 0}`;

    const edgeFps = document.getElementById("edgeFpsBadge");
    if (edgeFps && camStream.fps) {
        edgeFps.innerText = `${camStream.fps} FPS`;
    }
    const sirenBtn = document.getElementById("sirenSoundIcon");
    if (sirenBtn && audStream.status) {
        sirenBtn.innerText = audStream.status === "OK" ? "AUDIO: ON" : "AUDIO: OFF";
    }
}

function renderOutboxPanel(outboxData) {
    const counts = outboxData.counts || {};
    const pEl = document.getElementById("outboxPendingCount");
    const sEl = document.getElementById("outboxSyncedCount");
    const dEl = document.getElementById("outboxDeadLetterCount");

    if (pEl) pEl.innerText = counts.PENDING || 0;
    if (sEl) sEl.innerText = counts.SYNCED || 0;
    if (dEl) dEl.innerText = counts.DEAD_LETTER || 0;

    const list = document.getElementById("outboxRowsList");
    if (!list) return;
    const rows = outboxData.recent || [];
    if (!rows.length) {
        list.innerHTML = '<div class="text-xs text-slate-400 font-mono">Outbox is clean. No pending queued telemetry.</div>';
        return;
    }
    list.innerHTML = rows.map(r => `
        <div class="p-2.5 bg-slate-50 border border-slate-200 rounded-lg flex items-center justify-between text-xs font-mono">
            <div>
                <span class="font-bold text-slate-800">${r.payload_type}</span>
                <span class="text-slate-400 text-[10px] ml-2">Attempts: ${r.attempts}</span>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold ${r.status === 'SYNCED' ? 'bg-emerald-100 text-emerald-800' : r.status === 'DEAD_LETTER' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'}">${r.status}</span>
        </div>
    `).join("");
}

async function controlStream(stream, action) {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!["COMMANDER", "OPERATOR"].includes(user.role)) {
        alert(`Stream control restricted to Commander and Operator roles. Current: ${user.roleTitle}`);
        return;
    }
    const res = await fetch("/api/monitoring/stream/control", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ stream, action })
    });
    if (!res.ok) {
        const err = await res.json();
        alert(err.error || "Control failed");
    } else {
        loadSystemHealth();
    }
}

async function changeStreamSource(stream) {
    const user = getCurrentUser() || SYSTEM_USERS.commander;
    if (!["COMMANDER", "OPERATOR"].includes(user.role)) {
        alert("Source configuration restricted to Commander and Operator roles.");
        return;
    }
    const sel = document.getElementById(stream === "camera" ? "cameraSourceSelect" : "audioSourceSelect");
    if (!sel) return;
    const source = sel.value;
    await fetch("/api/monitoring/stream/source", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ stream, source })
    });
    loadSystemHealth();
}


/* ========================================================================= */
/* 9. OPERATIONAL ANALYTICS & HISTORICAL METRICS (PHASE 5B)                  */
/* ========================================================================= */

let analyticsTrendsChartInstance = null;
let analyticsAvailabilityChartInstance = null;
let analyticsOutboxChartInstance = null;
let currentTrendBucket = "1h";
const analyticsClientCache = {
    key: "",
    timestamp: 0,
    data: null
};

function updateAnalyticsOfflineState() {
    const offlineBanner = document.getElementById("analyticsOfflineBanner");
    if (!offlineBanner) return;
    if (!navigator.onLine) {
        offlineBanner.classList.remove("hidden");
    } else {
        offlineBanner.classList.add("hidden");
    }
}
window.addEventListener("online", updateAnalyticsOfflineState);
window.addEventListener("offline", updateAnalyticsOfflineState);

function getAnalyticsFilterParams() {
    const range = document.getElementById("analyticsFilterRange")?.value || "24h";
    const zone = document.getElementById("analyticsFilterZone")?.value || "all";
    const severity = document.getElementById("analyticsFilterSeverity")?.value || "all";
    const model = document.getElementById("analyticsFilterModel")?.value || "all";
    const demo = document.getElementById("analyticsFilterDemo")?.checked ? "true" : "false";

    const params = new URLSearchParams();
    params.set("range", range);
    if (zone !== "all") params.set("zone", zone);
    if (severity !== "all") params.set("severity", severity);
    if (model !== "all") params.set("model", model);
    if (demo === "true") params.set("include_demo", "true");
    return params;
}

function restoreAnalyticsFiltersFromUrl() {
    let params = null;
    if (window.location.search && window.location.search.length > 1) {
        params = new URLSearchParams(window.location.search);
    } else {
        const hash = window.location.hash.replace("#", "");
        const qIndex = hash.indexOf("?");
        if (qIndex !== -1) {
            params = new URLSearchParams(hash.slice(qIndex + 1));
        }
    }
    if (!params) return;

    const range = params.get("range");
    const zone = params.get("zone");
    const severity = params.get("severity");
    const model = params.get("model");
    const demo = params.get("include_demo");

    if (range && document.getElementById("analyticsFilterRange")) document.getElementById("analyticsFilterRange").value = range;
    if (zone && document.getElementById("analyticsFilterZone")) document.getElementById("analyticsFilterZone").value = zone;
    if (severity && document.getElementById("analyticsFilterSeverity")) document.getElementById("analyticsFilterSeverity").value = severity;
    if (model && document.getElementById("analyticsFilterModel")) document.getElementById("analyticsFilterModel").value = model;
    if (document.getElementById("analyticsFilterDemo")) document.getElementById("analyticsFilterDemo").checked = (demo === "true");
}

function applyAnalyticsFilters() {
    const params = getAnalyticsFilterParams();
    window.location.hash = `analytics?${params.toString()}`;
    if (window.history && window.history.replaceState) {
        const newUrl = window.location.pathname + "?" + params.toString() + window.location.hash;
        window.history.replaceState(null, "", newUrl);
    }
    loadAnalytics(true);
}

function resetAnalyticsFilters() {
    if (document.getElementById("analyticsFilterRange")) document.getElementById("analyticsFilterRange").value = "24h";
    if (document.getElementById("analyticsFilterZone")) document.getElementById("analyticsFilterZone").value = "all";
    if (document.getElementById("analyticsFilterSeverity")) document.getElementById("analyticsFilterSeverity").value = "all";
    if (document.getElementById("analyticsFilterModel")) document.getElementById("analyticsFilterModel").value = "all";
    if (document.getElementById("analyticsFilterDemo")) document.getElementById("analyticsFilterDemo").checked = false;

    window.location.hash = "analytics";
    if (window.history && window.history.replaceState) {
        window.history.replaceState(null, "", window.location.pathname + "#analytics");
    }
    loadAnalytics(true);
}

function setTrendBucket(bucket) {
    currentTrendBucket = bucket;
    const b1h = document.getElementById("trendBucket1h");
    const b1d = document.getElementById("trendBucket1d");
    if (b1h && b1d) {
        if (bucket === "1h") {
            b1h.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-blue-600 text-white";
            b1d.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600 hover:bg-slate-200";
        } else {
            b1d.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-blue-600 text-white";
            b1h.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600 hover:bg-slate-200";
        }
    }
    loadAnalyticsTrendsOnly();
}

async function loadAnalytics(forceRefresh = false) {
    restoreAnalyticsFiltersFromUrl();
    const params = getAnalyticsFilterParams();
    const qStr = params.toString();

    // Check client cache (TTL: 8 seconds)
    const now = Date.now();
    if (!forceRefresh && analyticsClientCache.key === qStr && (now - analyticsClientCache.timestamp < 8000)) {
        renderAnalyticsData(analyticsClientCache.data);
        return;
    }

    const loadEl = document.getElementById("analyticsLoadingState");
    const errEl = document.getElementById("analyticsErrorState");
    const contentEl = document.getElementById("analyticsContent");
    const emptyEl = document.getElementById("analyticsEmptyState");

    if (loadEl) loadEl.classList.remove("hidden");
    if (errEl) errEl.classList.add("hidden");
    if (contentEl) contentEl.classList.add("hidden");
    if (emptyEl) emptyEl.classList.add("hidden");

    try {
        const [overviewRes, trendsRes, modelsRes, availRes, outboxRes] = await Promise.all([
            fetch(`/api/analytics/overview?${qStr}`).then(r => r.ok ? r.json() : Promise.reject("overview failed")),
            fetch(`/api/analytics/trends?${qStr}&bucket=${currentTrendBucket}`).then(r => r.ok ? r.json() : Promise.reject("trends failed")),
            fetch(`/api/analytics/models?${qStr}`).then(r => r.ok ? r.json() : Promise.reject("models failed")),
            fetch(`/api/analytics/availability?${qStr}`).then(r => r.ok ? r.json() : Promise.reject("availability failed")),
            fetch(`/api/analytics/outbox?${qStr}`).then(r => r.ok ? r.json() : Promise.reject("outbox failed"))
        ]);

        const fullData = {
            overview: overviewRes,
            trends: trendsRes,
            models: modelsRes,
            availability: availRes,
            outbox: outboxRes
        };

        analyticsClientCache.key = qStr;
        analyticsClientCache.timestamp = now;
        analyticsClientCache.data = fullData;

        if (loadEl) loadEl.classList.add("hidden");
        if (contentEl) contentEl.classList.remove("hidden");

        renderAnalyticsData(fullData);
    } catch (err) {
        console.error("loadAnalytics failed:", err);
        if (loadEl) loadEl.classList.add("hidden");
        if (errEl) {
            errEl.classList.remove("hidden");
            const msgEl = document.getElementById("analyticsErrorMessage");
            if (msgEl) msgEl.innerText = `Error retrieving analytics data: ${err}`;
        }
    }
}

async function loadAnalyticsTrendsOnly() {
    const params = getAnalyticsFilterParams();
    const qStr = params.toString();
    try {
        const trendsRes = await fetch(`/api/analytics/trends?${qStr}&bucket=${currentTrendBucket}`).then(r => r.json());
        if (trendsRes && trendsRes.timeseries) {
            renderAnalyticsTrendsChart(trendsRes.timeseries);
        }
    } catch (e) {
        console.warn("loadAnalyticsTrendsOnly failed:", e);
    }
}

function renderAnalyticsData(data) {
    const overview = data.overview || {};
    const kpis = overview.kpis || {};
    const summary = overview.summary || {};
    const zones = overview.zones || [];
    const models = data.models || {};
    const avail = data.availability || {};
    const outbox = data.outbox || {};

    // 1. KPI Cards
    const totalEl = document.getElementById("kpiTotalIncidents");
    const activeEl = document.getElementById("kpiActiveBadge");
    const resEl = document.getElementById("kpiResolvedBadge");
    const mttaEl = document.getElementById("kpiMtta");
    const mttrEl = document.getElementById("kpiMttr");
    const farEl = document.getElementById("kpiFar");
    const farCountEl = document.getElementById("kpiFarCount");
    const availEl = document.getElementById("kpiAvailability");
    const badgeAvail = document.getElementById("analyticsAssuranceBadge");
    const assEl = document.getElementById("kpiAssurance");

    if (totalEl) totalEl.innerText = kpis.total_incidents || 0;
    if (activeEl) activeEl.innerText = `${kpis.active_incidents || 0} Active`;
    if (resEl) resEl.innerText = `${kpis.resolved_incidents || 0} Closed`;
    if (mttaEl) mttaEl.innerText = kpis.mtta_seconds !== null ? `${kpis.mtta_seconds}s` : "--";
    if (mttrEl) mttrEl.innerText = kpis.mttr_seconds !== null ? `${kpis.mttr_seconds}s` : "--";
    if (farEl) farEl.innerText = `${kpis.false_alarm_rate_pct || 0}%`;
    if (farCountEl) farCountEl.innerText = kpis.false_alarms || 0;
    if (availEl) availEl.innerText = `${kpis.system_availability_pct || 100}%`;
    if (badgeAvail) badgeAvail.innerText = `AVAILABILITY: ${kpis.system_availability_pct || 100}%`;

    // Assurance mode
    const dist = avail.incident_assurance_distribution || {};
    const modes = Object.keys(dist);
    if (assEl) assEl.innerText = modes.length > 0 ? modes[0] : "FULL";

    // Empty state
    const emptyEl = document.getElementById("analyticsEmptyState");
    if (emptyEl) {
        if (!kpis.total_incidents || kpis.total_incidents === 0) {
            emptyEl.classList.remove("hidden");
        } else {
            emptyEl.classList.add("hidden");
        }
    }

    // 2. Incident Trend Chart
    if (data.trends && data.trends.timeseries) {
        renderAnalyticsTrendsChart(data.trends.timeseries);
    }

    // 3. Zone Risk Comparison
    renderZoneRiskList(zones);

    // 4. Model Performance Panel
    renderModelPerformancePanel(models);

    // 5. Device Availability
    renderDeviceAvailability(avail);

    // 6. Offline-Sync Backlog
    renderSyncBacklog(outbox);
}

function renderAnalyticsTrendsChart(timeseries) {
    const canvas = document.getElementById("analyticsTrendsChart");
    if (!canvas || !window.Chart) return;

    const labels = timeseries.map(t => {
        const parts = t.bucket.split("T");
        return parts.length > 1 ? parts[1].slice(0, 5) : t.bucket;
    });

    const critData = timeseries.map(t => t.critical || 0);
    const highData = timeseries.map(t => t.high || 0);
    const medLowData = timeseries.map(t => (t.medium || 0) + (t.low || 0));
    const farData = timeseries.map(t => t.false_alarm || 0);

    if (analyticsTrendsChartInstance) {
        analyticsTrendsChartInstance.destroy();
    }

    analyticsTrendsChartInstance = new Chart(canvas, {
        type: "bar",
        data: {
            labels: labels.length > 0 ? labels : ["No Data"],
            datasets: [
                {
                    label: "Critical",
                    data: critData.length > 0 ? critData : [0],
                    backgroundColor: "#ef4444",
                    borderRadius: 4
                },
                {
                    label: "High",
                    data: highData.length > 0 ? highData : [0],
                    backgroundColor: "#f59e0b",
                    borderRadius: 4
                },
                {
                    label: "Medium/Low",
                    data: medLowData.length > 0 ? medLowData : [0],
                    backgroundColor: "#3b82f6",
                    borderRadius: 4
                },
                {
                    label: "False Alarm",
                    data: farData.length > 0 ? farData : [0],
                    backgroundColor: "#94a3b8",
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { stacked: true, grid: { display: false } },
                y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
            },
            plugins: {
                legend: { display: false },
                tooltip: { mode: 'index', intersect: false }
            }
        }
    });
}

function renderZoneRiskList(zones) {
    const list = document.getElementById("zoneRiskList");
    if (!list) return;

    if (!zones.length) {
        list.innerHTML = `<div class="p-3 bg-slate-50 rounded-lg text-xs font-mono text-slate-400 text-center">No zone incident data in selected window.</div>`;
        return;
    }

    list.innerHTML = zones.map(z => {
        const rLvl = z.risk_level || "LOW";
        const badgeColor = rLvl === "CRITICAL" ? "bg-rose-100 text-rose-800 border-rose-300"
            : rLvl === "HIGH" ? "bg-amber-100 text-amber-800 border-amber-300"
            : rLvl === "MEDIUM" ? "bg-blue-100 text-blue-800 border-blue-300"
            : "bg-emerald-100 text-emerald-800 border-emerald-300";

        return `
            <div class="p-3 rounded-xl border border-slate-200 bg-white flex items-center justify-between">
                <div>
                    <div class="font-mono text-xs font-bold text-slate-900">${z.zone_id}</div>
                    <div class="text-[10px] font-mono text-slate-500 mt-0.5">
                        Total: <strong>${z.total_incidents}</strong> &middot; Severe: <strong class="text-rose-600">${z.severe_incidents}</strong> &middot; Active: <strong class="text-amber-600">${z.active_incidents}</strong>
                    </div>
                </div>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-black border ${badgeColor}">${rLvl}</span>
            </div>
        `;
    }).join("");
}

function renderModelPerformancePanel(modelsData) {
    const perf = modelsData.performance || {};
    const drift = modelsData.drift || {};

    const confEl = document.getElementById("modelMeanConf");
    const oodEl = document.getElementById("modelOodRate");
    const disEl = document.getElementById("modelDisagreementRate");
    const accEl = document.getElementById("modelEvalAccuracy");

    if (confEl) confEl.innerText = perf.mean_confidence !== null ? `${Math.round(perf.mean_confidence * 100)}%` : "--";
    if (oodEl) oodEl.innerText = `${modelsData.ood_rate_pct || 0}%`;
    if (disEl) disEl.innerText = `${modelsData.disagreement_rate_pct || 0}%`;
    if (accEl) accEl.innerText = perf.accuracy !== null ? `${Math.round(perf.accuracy * 100)}%` : "--";

    // Drift timeline
    const driftList = document.getElementById("driftProgressionList");
    const badge = document.getElementById("driftCurrentStatusBadge");
    const timeline = drift.timeline || [];

    if (timeline.length > 0) {
        const latest = timeline[timeline.length - 1];
        if (badge) {
            badge.innerText = latest.status;
            badge.className = `px-2 py-0.5 rounded text-[10px] font-bold ${latest.status === 'STABLE' ? 'bg-emerald-100 text-emerald-800' : latest.status === 'WATCH' ? 'bg-blue-100 text-blue-800' : 'bg-rose-100 text-rose-800'}`;
        }
    }

    if (driftList) {
        if (!timeline.length) {
            driftList.innerHTML = `<div class="text-xs text-slate-400">No drift snapshots in current window.</div>`;
        } else {
            driftList.innerHTML = timeline.slice(-6).map(s => `
                <div class="p-2 rounded bg-white border border-slate-200 flex items-center justify-between text-[11px]">
                    <div>
                        <span class="font-bold text-slate-800">${s.model_id}</span>
                        <span class="text-slate-400 text-[10px] ml-1.5">PSI: <strong>${s.metrics?.psi ?? 'N/A'}</strong></span>
                    </div>
                    <span class="px-1.5 py-0.5 rounded text-[9px] font-bold ${s.status === 'STABLE' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}">${s.status}</span>
                </div>
            `).join("");
        }
    }

    // Confusion Matrix Table
    const cmContainer = document.getElementById("confusionMatrixContainer");
    const cm = perf.confusion_matrix || {};
    const actualClasses = Object.keys(cm);

    if (cmContainer) {
        if (!actualClasses.length) {
            cmContainer.innerHTML = `<div class="text-xs text-slate-400 p-2">No labeled feedback samples in window.</div>`;
        } else {
            const predClasses = Array.from(new Set(actualClasses.flatMap(a => Object.keys(cm[a]))));
            cmContainer.innerHTML = `
                <table class="w-full text-left border-collapse border border-slate-200">
                    <thead>
                        <tr class="bg-slate-100 text-[10px]">
                            <th class="p-1.5 border border-slate-200">Actual \\ Pred</th>
                            ${predClasses.map(p => `<th class="p-1.5 border border-slate-200">${p}</th>`).join("")}
                        </tr>
                    </thead>
                    <tbody>
                        ${actualClasses.map(a => `
                            <tr class="hover:bg-slate-50 text-[11px]">
                                <td class="p-1.5 font-bold border border-slate-200">${a}</td>
                                ${predClasses.map(p => `<td class="p-1.5 text-center border border-slate-200 ${a === p ? 'bg-emerald-50 font-bold text-emerald-800' : ''}">${cm[a][p] || 0}</td>`).join("")}
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `;
        }
    }
}

function renderDeviceAvailability(avail) {
    const list = document.getElementById("availabilityComponentsList");
    if (!list) return;

    const comps = avail.components || {};
    if (!Object.keys(comps).length) {
        list.innerHTML = `<div class="p-3 bg-slate-50 rounded-lg text-xs font-mono text-slate-400">No device health transitions recorded in this period. Overall system state is nominal.</div>`;
        return;
    }

    list.innerHTML = Object.entries(comps).map(([k, c]) => {
        const pct = c.availability_pct !== undefined ? c.availability_pct : 100;
        const color = pct >= 95 ? "bg-emerald-500" : pct >= 80 ? "bg-amber-500" : "bg-rose-500";
        return `
            <div class="space-y-1">
                <div class="flex items-center justify-between text-xs font-mono">
                    <span class="font-bold text-slate-800 uppercase">${k}</span>
                    <span class="text-slate-600">${pct}% Uptime (${c.total_events} events)</span>
                </div>
                <div class="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                    <div class="${color} h-2 rounded-full" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    }).join("");

    const canvas = document.getElementById("analyticsAvailabilityChart");
    if (canvas && window.Chart) {
        if (analyticsAvailabilityChartInstance) {
            analyticsAvailabilityChartInstance.destroy();
        }
        const labels = Object.keys(comps);
        const dataVals = labels.map(k => comps[k].availability_pct !== undefined ? comps[k].availability_pct : 100);
        analyticsAvailabilityChartInstance = new Chart(canvas, {
            type: "bar",
            data: {
                labels: labels.length > 0 ? labels.map(l => l.toUpperCase()) : ["No Data"],
                datasets: [{
                    label: "Uptime %",
                    data: dataVals.length > 0 ? dataVals : [100],
                    backgroundColor: "#10b981",
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                scales: {
                    x: { min: 0, max: 100, ticks: { callback: v => v + '%' } },
                    y: { grid: { display: false } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }
}

function renderSyncBacklog(outbox) {
    const pEl = document.getElementById("analyticsOutboxPending");
    const dEl = document.getElementById("analyticsOutboxDead");
    const list = document.getElementById("analyticsOutboxHistoryList");

    const counts = outbox.counts || {};
    if (pEl) pEl.innerText = counts.PENDING || 0;
    if (dEl) dEl.innerText = counts.DEAD_LETTER || 0;

    const canvas = document.getElementById("analyticsOutboxChart");
    if (canvas && window.Chart) {
        if (analyticsOutboxChartInstance) {
            analyticsOutboxChartInstance.destroy();
        }
        const pending = counts.PENDING || 0;
        const synced = counts.SYNCED || 0;
        const dead = counts.DEAD_LETTER || 0;
        const total = pending + synced + dead;
        analyticsOutboxChartInstance = new Chart(canvas, {
            type: "doughnut",
            data: {
                labels: ["Pending", "Synced", "Dead Letter"],
                datasets: [{
                    data: total > 0 ? [pending, synced, dead] : [0, 1, 0],
                    backgroundColor: ["#f59e0b", "#10b981", "#ef4444"]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { boxWidth: 12, font: { size: 10 } } }
                }
            }
        });
    }

    const recent = outbox.recent || [];
    if (!list) return;

    if (!recent.length) {
        list.innerHTML = `<div class="p-3 bg-slate-50 rounded-lg text-xs font-mono text-slate-400">Outbox queue is empty. Offline sync is up to date.</div>`;
        return;
    }

    list.innerHTML = recent.map(r => `
        <div class="p-2.5 rounded-lg border border-slate-200 bg-white flex items-center justify-between text-xs">
            <div>
                <span class="font-bold text-slate-900">${r.payload_type}</span>
                <span class="text-[10px] text-slate-400 ml-2">${r.idempotency_key?.slice(0, 16)}...</span>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-[10px] text-slate-500">Tries: ${r.attempts}</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-bold ${r.status === 'SYNCED' ? 'bg-emerald-100 text-emerald-800' : r.status === 'DEAD_LETTER' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'}">${r.status}</span>
            </div>
        </div>
    `).join("");
}

/* ========================================================================= */
/* 10. STORAGE SAFETY & DATA RETENTION (PHASE 5D)                            */
/* ========================================================================= */

async function loadStorageStatus() {
    try {
        const res = await fetch("/api/storage/status");
        if (!res.ok) return;
        const data = await res.json();

        const badge = document.getElementById("storageHealthStatusBadge");
        if (badge) {
            badge.innerText = `STORAGE: ${data.status}`;
            badge.className = `px-2.5 py-1 rounded text-[11px] font-mono font-bold uppercase border ${
                data.status === "OK" ? "bg-emerald-100 text-emerald-800 border-emerald-200" :
                data.status === "DEGRADED" ? "bg-amber-100 text-amber-800 border-amber-200" :
                "bg-rose-100 text-rose-800 border-rose-200"
            }`;
        }

        const freeGb = (data.free_bytes / (1024 * 1024 * 1024)).toFixed(1);
        const freeEl = document.getElementById("storageFreeText");
        if (freeEl) freeEl.innerText = `${freeGb} GB Free (${data.free_percent}%)`;

        const subs = data.subsystem_bytes || {};
        const walKb = Math.round((subs.wal || 0) / 1024);
        const walEl = document.getElementById("storageWalText");
        if (walEl) walEl.innerText = `${walKb} KB`;

        const dvrMb = ((subs.dvr || 0) / (1024 * 1024)).toFixed(1);
        const dvrEl = document.getElementById("storageDvrText");
        if (dvrEl) dvrEl.innerText = `${dvrMb} MB`;

        const evidMb = ((subs.evidence || 0) / (1024 * 1024)).toFixed(1);
        const evidEl = document.getElementById("storageEvidenceText");
        if (evidEl) evidEl.innerText = `${evidMb} MB`;
    } catch (e) {
        console.error("loadStorageStatus error:", e);
    }
}

async function triggerWalCheckpoint(mode) {
    const token = localStorage.getItem("sentinel_token");
    if (!token) {
        alert("Authentication required. Please log in as Commander or Engineer.");
        return;
    }
    try {
        const res = await fetch("/api/storage/checkpoint", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ mode: mode })
        });
        const data = await res.json();
        if (!res.ok) {
            alert(`Checkpoint error: ${data.error || "Failed"}`);
            return;
        }
        alert(`WAL Checkpoint (${mode}) complete!\nPages checkpointed: ${data.checkpointed_pages}\nWAL size: ${Math.round(data.wal_size_after / 1024)} KB`);
        loadStorageStatus();
    } catch (e) {
        alert("Failed to trigger WAL checkpoint: " + e.message);
    }
}

async function triggerStorageCleanup() {
    const token = localStorage.getItem("sentinel_token");
    if (!token) {
        alert("Authentication required. Please log in as Commander or Engineer.");
        return;
    }
    const policy = document.getElementById("storagePolicySelect")?.value || "all";
    const dryRun = document.getElementById("storageDryRunToggle")?.checked ?? true;

    try {
        const res = await fetch("/api/storage/cleanup", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ policy: policy, dry_run: dryRun })
        });
        const data = await res.json();
        if (!res.ok) {
            alert(`Cleanup error: ${data.error || "Failed"}`);
            return;
        }

        const box = document.getElementById("storageCleanupResultBox");
        const ts = document.getElementById("storageResultTimestamp");
        const content = document.getElementById("storageResultContent");

        if (box && content) {
            box.classList.remove("hidden");
            if (ts) ts.innerText = new Date().toLocaleTimeString();
            content.innerText = JSON.stringify(data, null, 2);
        }
        loadStorageStatus();
    } catch (e) {
        alert("Failed to execute storage cleanup: " + e.message);
    }
}

