import Social
import UniformTypeIdentifiers

final class ShareViewController: SLComposeServiceViewController {
    override func isContentValid() -> Bool { true }

    override func didSelectPost() {
        guard let item = extensionContext?.inputItems.first as? NSExtensionItem,
              let provider = item.attachments?.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.image.identifier) }) else {
            extensionContext?.cancelRequest(withError: NSError(domain: "SkywatcherShare", code: 1)); return
        }
        provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, error in
            Task {
                do {
                    guard let data else { throw error ?? NSError(domain: "SkywatcherShare", code: 2) }
                    _ = try await ScreenshotAnalyzer().analyze(data: data, sourceLabel: "share_extension")
                    self.extensionContext?.completeRequest(returningItems: nil)
                } catch {
                    self.extensionContext?.cancelRequest(withError: error)
                }
            }
        }
    }

    override func configurationItems() -> [Any]! { [] }
}
