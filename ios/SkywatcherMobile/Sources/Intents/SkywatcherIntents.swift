import AppIntents
import Foundation
import UniformTypeIdentifiers

struct AnalyzeSkywatcherScreenshotIntent: AppIntent {
    static let title: LocalizedStringResource = "Analyze Skywatcher Screenshot"
    static let description = IntentDescription("Analyze a manually captured screenshot entirely on device.")
    static let openAppWhenRun = false

    @Parameter(title: "Screenshot")
    var screenshot: IntentFile

    func perform() async throws -> some IntentResult & ReturnsValue<IntentFile> & ProvidesDialog {
        let result = try await ScreenshotAnalyzer().analyze(data: screenshot.data, sourceLabel: "shortcut")
        let output = try Data(contentsOf: result.manifestURL)
        return .result(value: IntentFile(data: output, filename: "skywatcher-\(result.runID.uuidString).json", type: .json), dialog: "Analysis completed locally.")
    }
}

struct SkywatcherShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AnalyzeSkywatcherScreenshotIntent(), phrases: ["Analyze screenshot with \(.applicationName)"], shortTitle: "Analyze Screenshot", systemImageName: "viewfinder")
    }
}
