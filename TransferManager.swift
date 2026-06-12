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

class TransferManager: NSObject, ObservableObject {
    @Published var state: TransferState = .idle
    private var connection: NWConnection?
    
    override init() {
        super.init()
    }
    
    func sendFile(url: URL, to device: DiscoveredDevice) {
        state = .connecting
        
        let endpoint = device.endpoint
        let parameters = NWParameters.tcp
        
        connection = NWConnection(to: endpoint, using: parameters)
        
        connection?.stateUpdateHandler = { [weak self] state in
            guard let self = self else { return }
            switch state {
            case .ready:
                print("TransferManager: Connection ready. Starting P2P Handshake...")
                self.startHandshake(url: url)
            case .failed(let error):
                print("TransferManager: Connection failed: \(error)")
                self.updateStateOnMain(.failed(error.localizedDescription))
            case .cancelled:
                print("TransferManager: Connection cancelled")
            default:
                break
            }
        }
        
        connection?.start(queue: .global())
    }
    
    private func startHandshake(url: URL) {
        guard let connection = connection else { return }
        
        // 1. Read file size
        let fileName = url.lastPathComponent
        let fileSize: Int64
        do {
            let resourceValues = try url.resourceValues(forKeys: [.fileSizeKey])
            fileSize = Int64(resourceValues.fileSize ?? 0)
        } catch {
            updateStateOnMain(.failed("Could not read file size"))
            connection.cancel()
            return
        }
        
        // 2. Prepare JSON metadata
        let metadata: [String: Any] = [
            "senderName": "iPhone",
            "fileName": fileName,
            "fileSize": fileSize
        ]
        
        guard let jsonData = try? JSONSerialization.data(withJSONObject: metadata),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            updateStateOnMain(.failed("Could not serialize metadata"))
            connection.cancel()
            return
        }
        
        let metaBytes = jsonString.data(using: .utf8)!
        let metaLength = Int32(metaBytes.count)
        
        // 3. Send metadata length (4 bytes big-endian)
        var lengthBigEndian = metaLength.bigEndian
        let lengthData = Data(bytes: &lengthBigEndian, count: MemoryLayout<Int32>.size)
        
        connection.send(content: lengthData, completion: .contentProcessed { [weak self] error in
            if let error = error {
                self?.updateStateOnMain(.failed("Failed to send metadata length: \(error)"))
                connection.cancel()
                return
            }
            
            // 4. Send metadata JSON string
            connection.send(content: metaBytes, completion: .contentProcessed { [weak self] error in
                if let error = error {
                    self?.updateStateOnMain(.failed("Failed to send metadata: \(error)"))
                    connection.cancel()
                    return
                }
                
                self?.updateStateOnMain(.sending(progress: 0.0))
                self?.waitForAcceptance(url: url, fileSize: fileSize)
            })
        })
    }
    
    private func waitForAcceptance(url: URL, fileSize: Int64) {
        guard let connection = connection else { return }
        
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            
            if let error = error {
                self.updateStateOnMain(.failed("Read response error: \(error)"))
                connection.cancel()
                return
            }
            
            guard let responseByte = data?.first else {
                self.updateStateOnMain(.failed("No response received"))
                connection.cancel()
                return
            }
            
            if responseByte == 0x01 { // Accepted
                print("TransferManager: Receiver accepted the file. Starting stream...")
                self.streamFile(url: url, fileSize: fileSize)
            } else { // Rejected
                self.updateStateOnMain(.failed("Receiver declined transfer"))
                connection.cancel()
            }
        }
    }
    
    private func streamFile(url: URL, fileSize: Int64) {
        guard let connection = connection else { return }
        
        guard let fileInputStream = InputStream(url: url) else {
            updateStateOnMain(.failed("Could not open file input stream"))
            connection.cancel()
            return
        }
        
        fileInputStream.open()
        
        let bufferSize = 65536
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
        var totalBytesSent: Int64 = 0
        
        func sendNextChunk() {
            if totalBytesSent >= fileSize {
                buffer.deallocate()
                fileInputStream.close()
                self.updateStateOnMain(.completed)
                connection.cancel()
                return
            }
            
            let readCount = fileInputStream.read(buffer, maxLength: bufferSize)
            if readCount < 0 {
                buffer.deallocate()
                fileInputStream.close()
                self.updateStateOnMain(.failed("Error reading file stream"))
                connection.cancel()
                return
            }
            
            if readCount == 0 {
                buffer.deallocate()
                fileInputStream.close()
                self.updateStateOnMain(.completed)
                connection.cancel()
                return
            }
            
            let chunkData = Data(bytes: buffer, count: readCount)
            connection.send(content: chunkData, completion: .contentProcessed { [weak self] error in
                guard let self = self else { return }
                if let error = error {
                    buffer.deallocate()
                    fileInputStream.close()
                    self.updateStateOnMain(.failed("Socket send error: \(error)"))
                    connection.cancel()
                    return
                }
                
                totalBytesSent += Int64(readCount)
                let progress = Double(totalBytesSent) / Double(fileSize)
                self.updateStateOnMain(.sending(progress: progress))
                
                sendNextChunk()
            })
        }
        
        sendNextChunk()
    }
    
    private func updateStateOnMain(_ state: TransferState) {
        DispatchQueue.main.async {
            self.state = state
        }
    }
}
