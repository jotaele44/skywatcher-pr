import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class ScreenshotAnalysisModel: ObservableObject {
    @Published var result: AnalysisResult?
    @Published var isWorking = false
    @Published var errorMessage: String?

    func analyze(data: Data, sourceLabel: String?) async {
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            result = try await ScreenshotAnalyzer().analyze(data: data, sourceLabel: sourceLabel)
        } catch {
            errorMessage = String(describing: error)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: ScreenshotAnalysisModel
    @State private var selectedItem: PhotosPickerItem?
    @State private var showImporter = false

    var body: some View {
        NavigationStack {
            List {
                Section("Manual intake") {
                    PhotosPicker(selection: $selectedItem, matching: .images) {
                        Label("Choose Screenshot", systemImage: "photo")
                    }
                    Button("Import from Files") { showImporter = true }
                }
                if model.isWorking { ProgressView("Analyzing locally…") }
                if let error = model.errorMessage {
                    Text(error).foregroundStyle(.red)
                }
                if let result = model.result {
                    Section("Result") {
                        LabeledContent("Run", value: result.runID.uuidString)
                        LabeledContent("SHA-256", value: result.source.sha256)
                        LabeledContent("OCR observations", value: "\(result.observations.count)")
                        LabeledContent("Confidence", value: result.confidence.formatted(.number.precision(.fractionLength(2))))
                        ShareLink(item: result.manifestURL) { Label("Export Manifest", systemImage: "square.and.arrow.up") }
                        if let imageURL = result.annotatedImageURL {
                            ShareLink(item: imageURL) { Label("Export Annotated Image", systemImage: "photo.badge.arrow.down") }
                        }
                    }
                }
            }
            .navigationTitle("Skywatcher")
            .task(id: selectedItem) {
                guard let selectedItem,
                      let data = try? await selectedItem.loadTransferable(type: Data.self) else { return }
                await model.analyze(data: data, sourceLabel: "photos")
            }
            .fileImporter(isPresented: $showImporter, allowedContentTypes: [.image]) { outcome in
                guard case let .success(url) = outcome else { return }
                Task {
                    let scoped = url.startAccessingSecurityScopedResource()
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    do { await model.analyze(data: try Data(contentsOf: url), sourceLabel: "files") }
                    catch { model.errorMessage = String(describing: error) }
                }
            }
        }
    }
}
