import Foundation
import Network

class ReceiverManager: ObservableObject {
    private var listener: NWListener?
    private let port: NWEndpoint.Port = 53317 // Default LocalSend port
    
    @Published var incomingTransfer: String?
    @Published var progress: Double = 0.0
    
    init() {
        startListening()
    }
    
    func startListening() {
        do {
            listener = try NWListener(using: .tcp, on: port)
            
            listener?.stateUpdateHandler = { state in
                print("Receiver Manager: State changed to \(state)")
            }
            
            listener?.newConnectionHandler = { [weak self] connection in
                self?.handleConnection(connection)
            }
            
            listener?.start(queue: .main)
        } catch {
            print("Receiver Manager: Failed to start listener: \(error)")
        }
    }
    
    private func handleConnection(_ connection: NWConnection) {
        connection.start(queue: .main)
        
        // Simplified HTTP Parsing for this prototype
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, context, isComplete, error in
            if let data = data, let request = String(data: data, encoding: .utf8) {
                if request.contains("POST") {
                    // Extract metadata (simplified)
                    DispatchQueue.main.async {
                        self?.incomingTransfer = "INCOMING FILE"
                        // In a real app, we'd parse the multipart body here
                        print("Receiver Manager: Received POST request")
                    }
                }
            }
            
            // For a real app, we would keep the connection open to stream the file
            // connection.send(...)
            connection.cancel()
        }
    }
}
