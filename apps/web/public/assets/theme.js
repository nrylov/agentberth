// Apply the saved preference before the page paints. Fresh installations use dark mode.
try {
  document.documentElement.dataset.theme =
    localStorage.getItem("agentberth-theme") === "light" ? "light" : "dark";
} catch {
  document.documentElement.dataset.theme = "dark";
}
