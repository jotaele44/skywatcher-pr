import CryptoKit
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Vision
#if canImport(UIKit)
import UIKit
#endif

struct SourceRecord: Codable, Equatable {
    let filename: String
    let sha256: String
    let byteCount: Int
    let width: Int
    let height: Int
    let captureMethod: String
    let sourceLabel: String?
}

struct TextObservation: Codable, Equatable, Identifiable {
    let id: UUID
    let text: String
    let confidence: Double
    let boundingBox: CGRect
}

struct AnalysisManifest: Codable, Equatable {
    let schemaVersion: String
    let runID: UUID
    let createdAt: Date
    let analyzerVersion: String
    let source: SourceRecord
    let observations: [TextObservation]
    let confidence: Double
    let contradictions: [String]
    let unresolvedFields: [String]
    let networkAccess: Bool
}

struct AnalysisResult {
    let runID: UUID
    let source: SourceRecord
    let observations: [TextObservation]
    let confidence: Double
    let manifestURL: URL
    let annotatedImageURL: URL?
}

enum AnalyzerError: LocalizedError {
    case emptyInput
    case oversizedInput(Int)
    case unsupportedImage
    case dimensionsExceeded(Int, Int)

    var errorDescription: String? {
        switch self {
        case .emptyInput: return "The selected file is empty."
        case let .oversizedInput(bytes): return "Input exceeds the 40 MiB limit (\(bytes) bytes)."
        case .unsupportedImage: return "Input is not a decodable image."
        case let .dimensionsExceeded(width, height): return "Image dimensions exceed the 20,000 pixel bound (\(width)×\(height))."
        }
    }
}

actor ScreenshotAnalyzer {
    static let maxBytes = 40 * 1024 * 1024
    static let maxDimension = 20_000

    func analyze(data: Data, sourceLabel: String?) async throws -> AnalysisResult {
        guard !data.isEmpty else { throw AnalyzerError.emptyInput }
        guard data.count <= Self.maxBytes else { throw AnalyzerError.oversizedInput(data.count) }
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              let image = CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCache: false] as CFDictionary)
        else { throw AnalyzerError.unsupportedImage }
        guard width <= Self.maxDimension, height <= Self.maxDimension else {
            throw AnalyzerError.dimensionsExceeded(width, height)
        }

        try Task.checkCancellation()
        let runID = UUID()
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let observations = try await recognizeText(image)
        try Task.checkCancellation()
        let sourceRecord = SourceRecord(
            filename: "source.bin", sha256: digest, byteCount: data.count,
            width: width, height: height, captureMethod: "manual_screenshot", sourceLabel: sourceLabel
        )
        let confidence = observations.isEmpty ? 0 : observations.map(\.confidence).reduce(0, +) / Double(observations.count)
        let manifest = AnalysisManifest(
            schemaVersion: "skywatcher.screenshot.analysis.v1", runID: runID, createdAt: Date(), analyzerVersion: "0.1.0",
            source: sourceRecord, observations: observations, confidence: confidence,
            contradictions: [], unresolvedFields: observations.isEmpty ? ["visible_text"] : ["icon_semantics", "marker_identity", "geolocation"],
            networkAccess: false
        )
        let directory = try EvidenceStore.makeRunDirectory(runID: runID)
        try data.write(to: directory.appendingPathComponent("source.bin"), options: .atomic)
        let manifestURL = try EvidenceStore.writeManifest(manifest, directory: directory)
        let annotatedURL = try EvidenceStore.writeAnnotatedImage(image, observations: observations, directory: directory)
        return AnalysisResult(runID: runID, source: sourceRecord, observations: observations, confidence: confidence, manifestURL: manifestURL, annotatedImageURL: annotatedURL)
    }

    private func recognizeText(_ image: CGImage) async throws -> [TextObservation] {
        try await withCheckedThrowingContinuation { continuation in
            let request = VNRecognizeTextRequest { request, error in
                if let error { continuation.resume(throwing: error); return }
                let rows = (request.results as? [VNRecognizedTextObservation] ?? []).compactMap { observation -> TextObservation? in
                    guard let candidate = observation.topCandidates(1).first else { return nil }
                    return TextObservation(id: UUID(), text: candidate.string, confidence: Double(candidate.confidence), boundingBox: observation.boundingBox)
                }
                continuation.resume(returning: rows)
            }
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.minimumTextHeight = 0.008
            DispatchQueue.global(qos: .userInitiated).async {
                do { try VNImageRequestHandler(cgImage: image).perform([request]) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }
}

enum EvidenceStore {
    static let appGroup = "group.org.prii.skywatcher.mobile"

    static func baseDirectory() throws -> URL {
        let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let directory = root.appendingPathComponent("Evidence", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    static func makeRunDirectory(runID: UUID) throws -> URL {
        let directory = try baseDirectory().appendingPathComponent(runID.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        return directory
    }

    static func writeManifest(_ manifest: AnalysisManifest, directory: URL) throws -> URL {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        let url = directory.appendingPathComponent("manifest.json")
        try encoder.encode(manifest).write(to: url, options: .atomic)
        return url
    }

    static func writeAnnotatedImage(_ image: CGImage, observations: [TextObservation], directory: URL) throws -> URL? {
        #if canImport(UIKit)
        let size = CGSize(width: image.width, height: image.height)
        let renderer = UIGraphicsImageRenderer(size: size)
        let rendered = renderer.image { context in
            UIImage(cgImage: image).draw(in: CGRect(origin: .zero, size: size))
            context.cgContext.setStrokeColor(UIColor.systemYellow.cgColor)
            context.cgContext.setLineWidth(max(2, size.width / 500))
            for item in observations {
                let box = item.boundingBox
                let rect = CGRect(x: box.minX * size.width, y: (1 - box.maxY) * size.height, width: box.width * size.width, height: box.height * size.height)
                context.cgContext.stroke(rect)
            }
        }
        guard let png = rendered.pngData() else { return nil }
        let url = directory.appendingPathComponent("annotated.png")
        try png.write(to: url, options: .atomic)
        return url
        #else
        return nil
        #endif
    }
}
