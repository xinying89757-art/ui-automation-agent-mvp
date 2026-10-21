Generate a real fixture module per business flow, exporting a default `FixtureHooks`
object from `../support/contracts.js`. Implement all four methods using observed UI
behavior. Read-only cases still verify their starting state and the unchanged baseline.
Prepare owned data on each invocation using `ctx.ownerMarker`. Cleanup must handle
partial preparation, and verify cleanup before the next independent attempt.
Never substitute empty hooks, fixed sleeps, unchecked clicks or API-based state setup.
Register each case's hooks file and explicit dynamic imports with the project CLI.
