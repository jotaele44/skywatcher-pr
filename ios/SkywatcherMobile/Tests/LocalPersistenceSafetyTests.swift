import CryptoKit
import Foundation
import SQLite3
import XCTest
@testable import SkywatcherMobile

/// Device-local regression tests. Executing these on Linux is AUDIT_ONLY,
/// not evidence of iOS lifecycle, device storage, or Floot-unreachable acceptance.
final class LocalPersistenceSafetyTests: XCTestCase {
    private var root: URL!
    private let hash = String(repeating: "a", count: 64)

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("mobile-safety-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: root)
    }

    private func path(_ name: String = "workspace.sqlite") -> URL { root.appendingPathComponent(name) }

    private func digest(_ url: URL) throws -> String {
        SHA256.hash(data: try Data(contentsOf: url)).map { String(format: "%02x", $0) }.joined()
    }

    private func rawDB(_ url: URL) throws -> OpaquePointer {
        var handle: OpaquePointer?
        let rc = sqlite3_open(url.path, &handle)
        guard rc == SQLITE_OK, let handle else {
            if let handle { sqlite3_close(handle) }
            throw MobilePersistenceError.integrityFailure
        }
        return handle
    }

    private func exec(_ db: OpaquePointer, _ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw MobilePersistenceError.database(String(cString: sqlite3_errmsg(db)))
        }
    }

    private func stage(_ store: MobilePersistenceStore, _ generation: String, _ ids: [String]) throws {
        try store.stageImport(generationID: generation, sourceSHA256: hash,
                              rawCount: ids.count, retainedCount: ids.count,
                              excludedCount: 0, unresolvedCount: 0, stableIDs: ids)
    }

    func testHashValidCorruptBackupPreservesCommittedWALBytes() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try store.setWorkspaceValue(key: "baseline", value: Data("old".utf8))
        let observer = try rawDB(path())
        defer { sqlite3_close(observer) }
        try exec(observer, "PRAGMA wal_checkpoint(TRUNCATE)")
        try store.setWorkspaceValue(key: "admitted", value: Data("committed-only-in-WAL".utf8))
        let wal = URL(fileURLWithPath: path().path + "-wal")
        let beforeMain = try Data(contentsOf: path())
        let beforeWAL = try Data(contentsOf: wal)
        XCTAssertGreaterThan(beforeWAL.count, 32)
        let bad = path("corrupt.sqlite")
        try Data("not a sqlite database".utf8).write(to: bad)
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(
            from: bad, expectedSHA256: digest(bad), to: path()))
        XCTAssertEqual(try Data(contentsOf: path()), beforeMain)
        XCTAssertEqual(try Data(contentsOf: wal), beforeWAL)
        XCTAssertEqual(try store.workspaceValue(key: "admitted"), Data("committed-only-in-WAL".utf8))
    }

    func testMigrationDigestTamperingFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.close()
        let db = try rawDB(path())
        try exec(db, "UPDATE schema_migrations SET sha256='" + String(repeating: "0", count: 64) + "'")
        sqlite3_close(db)
        XCTAssertThrowsError(try MobilePersistenceStore(databaseURL: path()))
    }

    func testFutureMigrationVersionFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.close()
        let db = try rawDB(path())
        try exec(db, "UPDATE schema_migrations SET version=99")
        sqlite3_close(db)
        XCTAssertThrowsError(try MobilePersistenceStore(databaseURL: path()))
    }

    func testMigrationNameTamperingFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.close()
        let db = try rawDB(path())
        try exec(db, "UPDATE schema_migrations SET name='different-authority'")
        sqlite3_close(db)
        XCTAssertThrowsError(try MobilePersistenceStore(databaseURL: path()))
    }

    func testNULKeyCannotOverwriteDifferentRawKey() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try store.setWorkspaceValue(key: "scope", value: Data("prior".utf8))
        XCTAssertThrowsError(try store.setWorkspaceValue(key: "scope\0suffix", value: Data("new".utf8)))
        XCTAssertEqual(try store.workspaceValue(key: "scope"), Data("prior".utf8))
    }

    func testNULStableIDRollsBackWholeImport() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try stage(store, "prior", ["A"])
        try store.activateGeneration("prior")
        XCTAssertThrowsError(try stage(store, "bad", ["B", "C\0suffix"]))
        XCTAssertNil(try store.importState(generationID: "bad"))
        XCTAssertEqual(try store.activeGenerationID(), "prior")
    }

    func testOverflowIsRejectedWithoutTrapping() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        XCTAssertThrowsError(try store.stageImport(
            generationID: "overflow", sourceSHA256: hash, rawCount: Int.max,
            retainedCount: Int.max, excludedCount: 1, unresolvedCount: 0, stableIDs: []))
        XCTAssertNil(try store.importState(generationID: "overflow"))
    }

    func testEmptyBlobRoundTripsWithoutBecomingSQLNull() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try store.setWorkspaceValue(key: "empty", value: Data())
        XCTAssertEqual(try store.workspaceValue(key: "empty"), Data())
    }

    func testBackupCannotTargetLiveDatabase() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try store.setWorkspaceValue(key: "prior", value: Data("safe".utf8))
        XCTAssertThrowsError(try store.createBackup(at: path()))
        XCTAssertTrue(FileManager.default.fileExists(atPath: path().path))
        XCTAssertEqual(try store.workspaceValue(key: "prior"), Data("safe".utf8))
    }

    func testExistingBackupIsNeverOverwritten() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        let backup = path("backup.sqlite")
        _ = try store.createBackup(at: backup)
        let before = try Data(contentsOf: backup)
        try store.setWorkspaceValue(key: "later", value: Data("new".utf8))
        XCTAssertThrowsError(try store.createBackup(at: backup))
        XCTAssertEqual(try Data(contentsOf: backup), before)
    }

    func testValidBackupRestoresToNewDestination() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try store.setWorkspaceValue(key: "value", value: Data("snapshot".utf8))
        let backup = path("backup.sqlite")
        let receipt = try store.createBackup(at: backup)
        let destination = path("new.sqlite")
        try MobilePersistenceStore.restoreBackup(from: backup, expectedSHA256: receipt.databaseSHA256, to: destination)
        let restored = try MobilePersistenceStore(databaseURL: destination)
        defer { try? restored.close() }
        XCTAssertEqual(try restored.workspaceValue(key: "value"), Data("snapshot".utf8))
    }

    func testUnrelatedSQLiteSourceIsRejected() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.setWorkspaceValue(key: "value", value: Data("prior".utf8))
        try store.close()
        let foreign = path("foreign.sqlite")
        let db = try rawDB(foreign)
        try exec(db, "CREATE TABLE aircraft_observations(id TEXT PRIMARY KEY)")
        sqlite3_close(db)
        let before = try Data(contentsOf: path())
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(from: foreign, expectedSHA256: digest(foreign), to: path()))
        XCTAssertEqual(try Data(contentsOf: path()), before)
    }

    func testProducerDestinationIsNotOverwritten() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        let backup = path("backup.sqlite")
        let receipt = try store.createBackup(at: backup)
        let foreign = path("producer.sqlite")
        let db = try rawDB(foreign)
        try exec(db, "CREATE TABLE flight_tracks(id TEXT PRIMARY KEY); INSERT INTO flight_tracks VALUES('P1')")
        sqlite3_close(db)
        let before = try Data(contentsOf: foreign)
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(from: backup, expectedSHA256: receipt.databaseSHA256, to: foreign))
        XCTAssertEqual(try Data(contentsOf: foreign), before)
    }

    func testHardLinkRestoreAliasIsRejected() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.close()
        let alias = path("alias.sqlite")
        try FileManager.default.linkItem(at: path(), to: alias)
        let before = try Data(contentsOf: path())
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(from: alias, expectedSHA256: digest(alias), to: path()))
        XCTAssertEqual(try Data(contentsOf: path()), before)
    }

    func testFailedActivationPreservesPriorGeneration() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        try stage(store, "prior", ["A"])
        try store.activateGeneration("prior")
        try stage(store, "damaged", ["B"])
        let db = try rawDB(path())
        defer { sqlite3_close(db) }
        try exec(db, "DELETE FROM import_record_ref WHERE generation_id='damaged'")
        XCTAssertThrowsError(try store.activateGeneration("damaged"))
        XCTAssertEqual(try store.activeGenerationID(), "prior")
        XCTAssertEqual(try store.importState(generationID: "prior"), "ACTIVE")
    }

    func testBlankGenerationIsRejected() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        defer { try? store.close() }
        XCTAssertThrowsError(try stage(store, " \n", ["A"]))
    }

    func testLockedDestinationRestorePreservesPriorValue() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.setWorkspaceValue(key: "value", value: Data("snapshot".utf8))
        let backup = path("backup.sqlite")
        let receipt = try store.createBackup(at: backup)
        try store.setWorkspaceValue(key: "value", value: Data("admitted".utf8))
        try store.close()
        let blocker = try rawDB(path())
        try exec(blocker, "BEGIN IMMEDIATE")
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(from: backup, expectedSHA256: receipt.databaseSHA256, to: path()))
        try exec(blocker, "ROLLBACK")
        sqlite3_close(blocker)
        let reopened = try MobilePersistenceStore(databaseURL: path())
        defer { try? reopened.close() }
        XCTAssertEqual(try reopened.workspaceValue(key: "value"), Data("admitted".utf8))
    }

    func testSchemaWildcardCannotHideExtraAuthorityTable() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        try store.close()
        let db = try rawDB(path())
        try exec(db, "CREATE TABLE sqliteXproducer_truth(id TEXT)")
        sqlite3_close(db)
        XCTAssertThrowsError(try MobilePersistenceStore(databaseURL: path()))
    }

    func testWrongDigestDoesNotTouchCurrentDatabase() throws {
        let store = try MobilePersistenceStore(databaseURL: path())
        let backup = path("backup.sqlite")
        _ = try store.createBackup(at: backup)
        try store.close()
        let before = try Data(contentsOf: path())
        XCTAssertThrowsError(try MobilePersistenceStore.restoreBackup(from: backup, expectedSHA256: hash, to: path()))
        XCTAssertEqual(try Data(contentsOf: path()), before)
    }

    func testFailedMigrationDoesNotAdoptUnrelatedDatabase() throws {
        let db = try rawDB(path())
        try exec(db, "CREATE TABLE producer_truth(id TEXT PRIMARY KEY); INSERT INTO producer_truth VALUES('P1')")
        sqlite3_close(db)
        let before = try Data(contentsOf: path())
        XCTAssertThrowsError(try MobilePersistenceStore(databaseURL: path()))
        XCTAssertEqual(try Data(contentsOf: path()), before)
    }
}
