// AUDIT_ONLY: Linux SHA256 bridge. Not Apple's CryptoKit and not an iOS test.
import Foundation
import COpenSSL
public enum SHA256 {
    public static func hash(data: Data) -> [UInt8] {
        var result = [UInt8](repeating: 0, count: 32)
        data.withUnsafeBytes { input in
            result.withUnsafeMutableBufferPointer { output in
                _ = COpenSSL.SHA256(input.bindMemory(to: UInt8.self).baseAddress,
                                   input.count, output.baseAddress)
            }
        }
        return result
    }
}
