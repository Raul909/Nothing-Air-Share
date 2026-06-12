import Foundation
import Network

class ReceiverManager: ObservableObject {
    private var listener: NWListener?
    private let port: NWEndpoint.Port = 53317 // Default LocalSend port
    
    @Published var incomingTransfer: String?
    @Published var progress: Double = 0.0
    
    private var currentFileHandle: FileHandle?
    private var tempFileURL: URL?
    
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
        
        // Prepare temporary file for streaming
        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "incoming_\(UUID().uuidString).bin"
        tempFileURL = tempDir.appendingPathComponent(fileName)
        
        FileManager.default.createFile(atPath: tempFileURL!.path, contents: nil, attributes: nil)
        
        do {
            currentFileHandle = try FileHandle(forWritingTo: tempFileURL!)
        } catch {
            print("Receiver Manager: Failed to create file handle: \(error)")
            connection.cancel()
            return
        }
        
        DispatchQueue.main.async {
            self.incomingTransfer = "RECEIVING..."
            self.progress = 0.0
        }
        
        receiveData(on: connection)
    }
    
    private func receiveData(on connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, context, isComplete, error in
            guard let self = self else { return }
            
            if let data = data, !data.isEmpty {
                try? self.currentFileHandle?.seekToEnd()
                self.currentFileHandle?.write(data)
                
                // Note: Without a protocol header, we don't know the total size here.
                // In a production app, we'd parse the HTTP Content-Length.
            }
            
            if isComplete {
                self.finalizeTransfer()
                connection.cancel()
            } else if let error = error {
                print("Receiver Manager: Receive error: \(error)")
                connection.cancel()
            } else {
                self.receiveData(on: connection)
            }
        }
    }
    
    private func finalizeTransfer() {
        try? currentFileHandle?.close()
        currentFileHandle = nil
        
        print("Receiver Manager: Transfer complete. Saved to \(tempFileURL?.path ?? "unknown")")
        
        DispatchQueue.main.async {
            self.incomingTransfer = "FINISHED"
            self.progress = 1.0
            
            // Logic to move the file to a permanent location (e.g. Downloads or Photos)
            // can be added here based on detected file type.
        }
    }
}
