# La telecamera che gira attorno al pianeta.
#
# Orbita e distanza invece di posizione e rotazione: il pianeta e' una sfera e lo si guarda
# sempre da fuori, quindi le coordinate naturali sono "da che parte" e "da quanto lontano".
# Con una telecamera libera si finisce dentro al pianeta al primo trascinamento storto, e da
# dentro una sfera non si vede niente -- il che somiglia molto a un programma rotto.
extends Camera3D

## Quanto ci si puo' avvicinare e allontanare. Il minimo sta appena sopra la superficie: piu'
## vicino si entrerebbe nel terreno.
const NEAR_LIMIT := 1.02
const FAR_LIMIT := 6.0

## Quanto si scende e si sale, al massimo. Oltre il polo la vista si capovolgerebbe, e un
## pianeta che si ribalta mentre lo si guarda e' il modo piu' rapido di perdere l'orientamento.
const PITCH_LIMIT := PI / 2.0 - 0.02

@export var distance := 2.30
@export var drag_speed := 0.006
@export var zoom_step := 1.12

var yaw := 0.0
var pitch := 0.3
var dragging := false


func _ready() -> void:
	near = 0.01
	place()


## Guarda da questa direzione, a questa distanza. La direzione e' un punto sulla sfera:
## "portami sopra quel posto".
func aim(direction: Vector3, from_distance: float = -1.0) -> void:
	var unit := direction.normalized()
	if from_distance > 0.0:
		distance = clampf(from_distance, NEAR_LIMIT, FAR_LIMIT)
	pitch = clampf(asin(clampf(unit.y, -1.0, 1.0)), -PITCH_LIMIT, PITCH_LIMIT)
	yaw = atan2(unit.x, unit.z)
	place()


func place() -> void:
	var eye := Vector3(
		sin(yaw) * cos(pitch),
		sin(pitch),
		cos(yaw) * cos(pitch)) * distance
	look_at_from_position(eye, Vector3.ZERO, Vector3.UP)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var button := event as InputEventMouseButton
		if button.button_index == MOUSE_BUTTON_LEFT:
			dragging = button.pressed
		elif button.pressed and button.button_index == MOUSE_BUTTON_WHEEL_UP:
			distance = clampf(distance / zoom_step, NEAR_LIMIT, FAR_LIMIT)
			place()
		elif button.pressed and button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			distance = clampf(distance * zoom_step, NEAR_LIMIT, FAR_LIMIT)
			place()
	elif event is InputEventMouseMotion and dragging:
		var motion := event as InputEventMouseMotion
		# Piu' si e' vicini, meno si gira: altrimenti da vicino un centimetro di mouse
		# spazzerebbe mezzo pianeta e non si riuscirebbe a fermarsi su una casella.
		var scale := drag_speed * clampf(distance - 1.0, 0.12, 4.0)
		yaw -= motion.relative.x * scale
		pitch = clampf(pitch + motion.relative.y * scale, -PITCH_LIMIT, PITCH_LIMIT)
		place()
