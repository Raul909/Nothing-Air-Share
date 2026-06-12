import Foundation
import Network

class ReceiverManager: ObservableObject {
    private var listener: NWListener?
    private let port: NWEndpoint.Port = 53317
    
    @Published var incomingTransfer: String?
    @Published var progress: Double = 0.0
    
    private var currentFileHandle: FileHandle?
    private var targetFileURL: URL?
    private var receivedBytes: Int64 = 0
    private var totalBytesExpected: Int64 = 0
    
    init() {
        startListening()
    }
    
    func startListening() {
        do {
            listener = try NWListener(using: .tcp, on: port)
            
            listener?.stateUpdateHandler = { state in
                print("ReceiverManager: State changed to \(state)")
            }
            
            listener?.newConnectionHandler = { [weak self] connection in
                self?.handleConnection(connection)
            }
            
            listener?.start(queue: .main)
            print("ReceiverManager: Listening on TCP port \(port)")
        } catch {
            print("ReceiverManager: Failed to start listener: \(error)")
        }
    }
    
    private func handleConnection(_ connection: NWConnection) {
        connection.start(queue: .main)
        print("ReceiverManager: Received incoming connection from \(connection.endpoint)")
        
        // 1. Read metadata length (4 bytes big-endian)
        connection.receive(minimumIncompleteLength: 4, maximumLength: 4) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            if let error = error {
                print("ReceiverManager: Error receiving length: \(error)")
                connection.cancel()
                return
            }
            
            guard let lengthData = data, lengthData.count == 4 else {
                print("ReceiverManager: Invalid length bytes")
                connection.cancel()
                return
            }
            
            let metaLength = Int(Int32(bigEndian: lengthData.withUnsafeBytes { $0.load(as: Int32.self) }))
            if metaLength <= 0 || metaLength > 1024 * 1024 {
                print("ReceiverManager: Meta length out of bounds: \(metaLength)")
                connection.cancel()
                return
            }
            
            self.readMetadata(connection: connection, length: metaLength)
        }
    }
    
    private func readMetadata(connection: NWConnection, length: Int) {
        // 2. Read metadata JSON string
        connection.receive(minimumIncompleteLength: length, maximumLength: length) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            if let error = error {
                print("ReceiverManager: Error receiving metadata: \(error)")
                connection.cancel()
                return
            }
            
            guard let metaData = data, metaData.count == length else {
                print("ReceiverManager: Metadata incomplete")
                connection.cancel()
                return
            }
            
            guard let json = try? JSONSerialization.jsonObject(with: metaData) as? [String: Any] else {
                print("ReceiverManager: Failed to parse metadata JSON")
                connection.cancel()
                return
            }
            
            let sender = json["senderName"] as? String ?? "Unknown Device"
            let filename = json["fileName"] as? String ?? "file.bin"
            let fileSize = json["fileSize"] as? Int64 ?? 0
            
            print("ReceiverManager: Incoming file '\(filename)' (\(fileSize) bytes) from \(sender)")
            
            // 3. Auto-accept for prototype (in production, prompt user)
            // Send back acceptance byte 0x01
            let acceptData = Data([0x01])
            connection.send(content: acceptData, completion: .contentProcessed { [weak self] error in
                guard let self = self else { return }
                if let error = error {
                    print("ReceiverManager: Failed to send acceptance: \(error)")
                    connection.cancel()
                    return
                }
                
                self.prepareFileForReceiving(fileName: filename, fileSize: fileSize)
                self.receivePayload(connection: connection)
            })
        }
    }
    
    private func prepareFileForReceiving(fileName: String, fileSize: Int64) {
        let docsDir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let targetDir = docsDir.appendingPathComponent("NothingDrop", isDirectory: true)
        
        // Ensure folder exists
        try? FileManager.default.createDirectory(at: targetDir, withIntermediateDirectories: true)
        
        var fileURL = targetDir.appendingPathComponent(fileName)
        var counter = 1
        let baseName = fileURL.deletingPathExtension().lastPathComponent
        let ext = fileURL.pathExtension
        
        while FileManager.default.fileExists(atPath: fileURL.path) {
            let newName = ext.isEmpty ? "\(baseName)-\(counter)" : "\(baseName)-\(counter).\(ext)"
            fileURL = targetDir.appendingPathComponent(newName)
            counter += 1
        }
        
        targetFileURL = fileURL
        totalBytesExpected = fileSize
        receivedBytes = 0
        
        FileManager.default.createFile(atPath: targetFileURL!.path, contents: nil, attributes: nil)
        
        do {
            currentFileHandle = try FileHandle(forWritingTo: targetFileURL!)
        } catch {
            print("ReceiverManager: Failed to create file handle: \(error)")
        }
        
        DispatchQueue.main.async {
            self.incomingTransfer = "Receiving: \(fileName)"
            self.progress = 0.0
        }
    }
    
    private func receivePayload(connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            
            if let chunk = data, !chunk.isEmpty {
                try? self.currentFileHandle?.seekToEnd()
                self.currentFileHandle?.write(chunk)
                self.receivedBytes += Int64(chunk.count)
                
                let currentProgress = self.totalBytesExpected > 0 ? Double(self.receivedBytes) / Double(self.totalBytesExpected) : 0.0
                DispatchQueue.main.async {
                    self.progress = currentProgress
                }
            }
            
            if self.receivedBytes >= self.totalBytesExpected || isComplete {
                self.finalizeTransfer()
                connection.cancel()
            } else if let error = error {
                print("ReceiverManager: Payload error: \(error)")
                connection.cancel()
            } else {
                self.receivePayload(connection: connection)
            }
        }
    }
    
    private func finalizeTransfer() {
        try? currentFileHandle?.close()
        currentFileHandle = nil
        
        print("ReceiverManager: Transfer complete. Saved to \(targetFileURL?.path ?? "unknown")")
        
        DispatchQueue.main.async {
            self.incomingTransfer = "Success: Saved in Documents/NothingDrop"
            self.progress = 1.0
        }
    }
}
