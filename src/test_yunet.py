
import cv2

model = "models/face_detection_yunet_2023mar.onnx"

detector = cv2.FaceDetectorYN.create(
    model,
    "",
    (640, 480),
    0.8,
    0.3,
    5000
)

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Camera not detected!")
    exit()

print("YuNet is running. Press Q to exit.")

while True:
    ret, frame = camera.read()

    if not ret:
        print("Cannot read camera.")
        break

    height, width = frame.shape[:2]
    detector.setInputSize((width, height))

    _, faces = detector.detect(frame)

    if faces is not None:
        for face in faces:
            x, y, w, h = face[:4].astype(int)

            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "FACE DETECTED",
                (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

    cv2.imshow("YuNet Face Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()
