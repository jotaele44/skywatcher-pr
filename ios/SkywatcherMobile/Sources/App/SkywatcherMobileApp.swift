import SwiftUI

@main
struct SkywatcherMobileApp: App {
    @StateObject private var model = ScreenshotAnalysisModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}
