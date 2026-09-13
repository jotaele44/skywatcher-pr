import XCTest
@testable import SkywatcherMobile

final class LocalPersistenceTests: XCTestCase {
    private func temporaryURL(_ name: String = "mobile.sqlite") -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("skywatcher-mobile-tests-\(UUID().uuidString)", isDirectory: true)
            .appendingPathComponent(name)
    }

    private let shaA = String(repeating: "a", count: 64)
    private let shaB = String(repeating: "b", count: 64)

    func testMigrationIsIdempotentAndWorkspacePersistsAcrossReopen() throws {
        let url = temporaryURL()
        var store: MobilePersistenceStore? = try MobilePersistenceStore(databaseURL: url)
        XCTAssertEqual(try store?.schemaVersion(), 1)
        let payload = Data("{\"mode\":\"offline\"}".utf8)
        try store?.setWorkspaceValue(key: "session", value: payload)
        try store?.close()
        store = nil

        let reopened = try MobilePersistenceStore(databaseURL: url)
        XCTAssertEqual(try reopened.schemaVersion(), 1)
        XCTAssertEqual(try reopened.workspaceValue(key: "session"), payload)
    }

    func testRawArithmeticMismatchFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        XCTAssertThrowsError(
            try store.stageImport(
                generationID: "bad-arithmetic",
                sourceSHA256: shaA,
                rawCount: 4,
                retainedCount: 2,
                excludedCount: 1,
                unresolvedCount: 0,
                stableIDs: ["A", "B"]
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .arithmeticMismatch)
        }
        XCTAssertNil(try store.importState(generationID: "bad-arithmetic"))
    }

    func testDuplicateStableIDFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        XCTAssertThrowsError(
            try store.stageImport(
                generationID: "duplicate",
                sourceSHA256: shaA,
                rawCount: 2,
                retainedCount: 2,
                excludedCount: 0,
                unresolvedCount: 0,
                stableIDs: ["A", "A"]
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .duplicateStableID)
        }
        XCTAssertNil(try store.importState(generationID: "duplicate"))
    }

    func testStagedGenerationCannotDisplaceActiveGeneration() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        try store.stageImport(
            generationID: "generation-1",
            sourceSHA256: shaA,
            rawCount: 2,
            retainedCount: 1,
            excludedCount: 1,
            unresolvedCount: 0,
            stableIDs: ["A"]
        )
        try store.activateGeneration("generation-1")
        XCTAssertEqual(try store.activeGenerationID(), "generation-1")

        try store.stageImport(
            generationID: "generation-2",
            sourceSHA256: shaB,
            rawCount: 3,
            retainedCount: 2,
            excludedCount: 0,
            unresolvedCount: 1,
            stableIDs: ["B", "C"]
        )

        XCTAssertEqual(try store.activeGenerationID(), "generation-1")
        XCTAssertEqual(try store.importState(generationID: "generation-2"), "STAGED")
    }

    func testActivationRetiresPreviousGenerationAtomically() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        try store.stageImport(
            generationID: "generation-1",
            sourceSHA256: shaA,
            rawCount: 1,
            retainedCount: 1,
            excludedCount: 0,
            unresolvedCount: 0,
            stableIDs: ["A"]
        )
        try store.activateGeneration("generation-1")

        try store.stageImport(
            generationID: "generation-2",
            sourceSHA256: shaB,
            rawCount: 1,
            retainedCount: 1,
            excludedCount: 0,
            unresolvedCount: 0,
            stableIDs: ["B"]
        )
        try store.activateGeneration("generation-2")

        XCTAssertEqual(try store.importState(generationID: "generation-1"), "RETIRED")
        XCTAssertEqual(try store.importState(generationID: "generation-2"), "ACTIVE")
        XCTAssertEqual(try store.activeGenerationID(), "generation-2")
    }

    func testHashBoundBackupAndRestore() throws {
        let databaseURL = temporaryURL()
        let backupURL = databaseURL.deletingLastPathComponent().appendingPathComponent("backup.sqlite")

        var store: MobilePersistenceStore? = try MobilePersistenceStore(databaseURL: databaseURL)
        try store?.setWorkspaceValue(key: "state", value: Data("original".utf8))
        let receipt = try XCTUnwrap(store?.createBackup(at: backupURL))
        XCTAssertEqual(receipt.databaseSHA256.count, 64)
        XCTAssertGreaterThan(receipt.byteCount, 0)

        try store?.setWorkspaceValue(key: "state", value: Data("changed".utf8))
        try store?.close()
        store = nil

        try MobilePersistenceStore.restoreBackup(
            from: backupURL,
            expectedSHA256: receipt.databaseSHA256,
            to: databaseURL
        )
        let restored = try MobilePersistenceStore(databaseURL: databaseURL)
        XCTAssertEqual(try restored.workspaceValue(key: "state"), Data("original".utf8))
    }

    func testTamperedBackupIsRejectedWithoutReplacingCurrentDatabase() throws {
        let databaseURL = temporaryURL()
        let backupURL = databaseURL.deletingLastPathComponent().appendingPathComponent("backup.sqlite")

        var store: MobilePersistenceStore? = try MobilePersistenceStore(databaseURL: databaseURL)
        try store?.setWorkspaceValue(key: "state", value: Data("current".utf8))
        let receipt = try XCTUnwrap(store?.createBackup(at: backupURL))
        try store?.close()
        store = nil

        var tampered = try Data(contentsOf: backupURL)
        tampered.append(0x00)
        try tampered.write(to: backupURL, options: .atomic)

        XCTAssertThrowsError(
            try MobilePersistenceStore.restoreBackup(
                from: backupURL,
                expectedSHA256: receipt.databaseSHA256,
                to: databaseURL
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .backupHashMismatch)
        }

        let reopened = try MobilePersistenceStore(databaseURL: databaseURL)
        XCTAssertEqual(try reopened.workspaceValue(key: "state"), Data("current".utf8))
    }
}
