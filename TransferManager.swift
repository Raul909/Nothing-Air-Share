import Foundation
import Network
import UniformTypeIdentifiers

enum TransferState {
    case idle
    case connecting
    case sending(progress: Double)
    case receiving(progress: Double)
    case completed
    case failed(String)
}

class TransferManager: ObservableObject {
    @Published var state: TransferState = .idle
    
    // In a real app, this would be the port the receiver is listening on
    private let receiverPort: UInt16 = 53317 
    
    func sendFile(url: URL, to device: DiscoveredDevice) {
        state = .connecting
        
        // 1. Resolve endpoint to IP address
        // For simplicity in this prototype, we'll assume the endpoint can be reached via URLSession 
        // if we convert it to a host string.
        
        guard case let .bonjourService(name, type, domain, _) = device.endpoint else {
            state = .failed("Invalid device endpoint")
            return
        }
        
        // Construct local URL. Bonjour services on iOS can often be reached via name.local
        let host = "\(name).\(domain)"
        let targetURL = URL(string: "http://\(host):\(receiverPort)/api/localsend/upload")!
        
        var request = URLRequest(url: targetURL)
        request.httpMethod = "POST"
        
        // Simplified multipart upload
        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        
        do {
            let fileData = try Data(contentsOf: url)
            let fileName = url.lastPathComponent
            let mimeType = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            
            var body = Data()
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
            body.append(fileData)
            body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
            
            let task = URLSession.shared.uploadTask(with: request, from: body) { data, response, error in
                DispatchQueue.main.async {
                    if let error = error {
                        self.state = .failed(error.localizedDescription)
                        return
                    }
                    
                    if let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) {
                        self.state = .completed
                    } else {
                        self.state = .failed("Server returned error")
                    }
                }
            }
            
            state = .sending(progress: 0.0)
            task.resume()
            
        } catch {
            state = .failed("Could not read file: \(error.localizedDescription)")
        }
    }
}
