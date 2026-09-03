import XCTest
@testable import SkywatcherMobile

final class ScreenshotAnalyzerTests: XCTestCase {
    func testEmptyInputFailsClosed() async {
        do {
            _ = try await ScreenshotAnalyzer().analyze(data: Data(), sourceLabel: nil)
            XCTFail("Expected empty input rejection")
        } catch AnalyzerError.emptyInput {
            XCTAssertTrue(true)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testOversizedInputFailsClosed() async {
        let data = Data(count: ScreenshotAnalyzer.maxBytes + 1)
        do {
            _ = try await ScreenshotAnalyzer().analyze(data: data, sourceLabel: nil)
            XCTFail("Expected size rejection")
        } catch AnalyzerError.oversizedInput {
            XCTAssertTrue(true)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testManifestEncodingIsDeterministicByKeys() throws {
        let manifest = AnalysisManifest(
            schemaVersion: "skywatcher.screenshot.analysis.v1", runID: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!,
            createdAt: Date(timeIntervalSince1970: 0), analyzerVersion: "0.1.0",
            source: SourceRecord(filename: "source.bin", sha256: String(repeating: "0", count: 64), byteCount: 1, width: 1, height: 1, captureMethod: "manual_screenshot", sourceLabel: nil),
            observations: [], confidence: 0, contradictions: [], unresolvedFields: ["visible_text"], networkAccess: false
        )
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        let json = String(decoding: try encoder.encode(manifest), as: UTF8.self)
        XCTAssertTrue(json.contains("\"networkAccess\":false"))
        XCTAssertTrue(json.contains("skywatcher.screenshot.analysis.v1"))
    }
}
