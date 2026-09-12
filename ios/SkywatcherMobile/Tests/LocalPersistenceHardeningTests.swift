import XCTest
@testable import SkywatcherMobile

final class LocalPersistenceHardeningTests: XCTestCase {
    private func temporaryURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("skywatcher-mobile-hardening-\(UUID().uuidString)", isDirectory: true)
            .appendingPathComponent("mobile.sqlite")
    }

    private let sha = String(repeating: "a", count: 64)

    func testEveryRetainedRecordRequiresAStableID() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        XCTAssertThrowsError(
            try store.stageImport(
                generationID: "missing-id",
                sourceSHA256: sha,
                rawCount: 2,
                retainedCount: 2,
                excludedCount: 0,
                unresolvedCount: 0,
                stableIDs: ["only-one"]
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .invalidCount)
        }
        XCTAssertNil(try store.importState(generationID: "missing-id"))
    }

    func testBlankStableIDFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        XCTAssertThrowsError(
            try store.stageImport(
                generationID: "blank-id",
                sourceSHA256: sha,
                rawCount: 1,
                retainedCount: 1,
                excludedCount: 0,
                unresolvedCount: 0,
                stableIDs: ["  \n"]
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .invalidStableID)
        }
        XCTAssertNil(try store.importState(generationID: "blank-id"))
    }

    func testNonASCIIHashLookalikeFailsClosed() throws {
        let store = try MobilePersistenceStore(databaseURL: temporaryURL())
        let fullWidthA = String(repeating: "ａ", count: 64)
        XCTAssertThrowsError(
            try store.stageImport(
                generationID: "unicode-hash",
                sourceSHA256: fullWidthA,
                rawCount: 0,
                retainedCount: 0,
                excludedCount: 0,
                unresolvedCount: 0,
                stableIDs: []
            )
        ) { error in
            XCTAssertEqual(error as? MobilePersistenceError, .invalidSHA256)
        }
        XCTAssertNil(try store.importState(generationID: "unicode-hash"))
    }
}
