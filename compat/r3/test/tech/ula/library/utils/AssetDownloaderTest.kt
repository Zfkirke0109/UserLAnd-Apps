package tech.ula.library.utils

/*
 * The upstream AssetDownloaderTest exercised DownloadManagerWrapper: enqueueing
 * into the OEM download provider, polling its cursor for status, and mapping its
 * failure reason codes. None of that survives r3, which owns its transfers.
 *
 * The replacement coverage lives in the r3 suites, which test the same concerns
 * against real HTTP rather than against a mocked provider:
 *
 *   R3ResumableAssetTransferTest  resume, verification, retry, atomic publish
 *   R3DownloadJournalTest         durable batch state across process death
 *   R3AssetDownloadPlannerTest    batch construction, outcomes, reconciliation
 *   R3AssetDownloadRunnerTest     ordering, durability, terminal failure
 *   R3AssetDownloadSignalsTest    in-process delivery of outcomes
 */
