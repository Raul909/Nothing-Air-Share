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

class TransferManager: NSObject, ObservableObject, URLSessionTaskDelegate {
    @Published var state: TransferState = .idle
    
    private let receiverPort: UInt16 = 53317 
    private var session: URLSession?
    
    override init() {
        super.init()
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        self.session = URLSession(configuration: config, delegate: self, delegateQueue: .main)
    }
    
    func sendFile(url: URL, to device: DiscoveredDevice) {
        state = .connecting
        
        guard case let .bonjourService(name, _, domain, _) = device.endpoint else {
            state = .failed("Invalid device endpoint")
            return
        }
        
        // Construct target URL
        let host = "\(name).\(domain)"
        let targetURL = URL(string: "http://\(host):\(receiverPort)/api/localsend/upload")!
        
        var request = URLRequest(url: targetURL)
        request.httpMethod = "POST"
        
        // Use a session upload task with a FILE URL for streaming (Low RAM usage)
        // Note: For a true LocalSend protocol, we'd need to wrap this in a multipart stream.
        // For this optimized prototype, we'll stream the raw bits and assume the receiver handles it.
        
        let task = session?.uploadTask(with: request, fromFile: url)
        task?.resume()
        
        DispatchQueue.main.async {
            self.state = .sending(progress: 0.0)
        }
    }
    
    // MARK: - URLSessionTaskDelegate
    
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        let progress = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
        DispatchQueue.main.async {
            if case .sending = self.state {
                self.state = .sending(progress: progress)
            }
        }
    }
    
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        DispatchQueue.main.async {
            if let error = error {
                self.state = .failed(error.localizedDescription)
            } else {
                self.state = .completed
            }
        }
    }
}
