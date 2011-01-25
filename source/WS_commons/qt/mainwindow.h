#include <QtGui/QApplication>
#include "ui_mainwindow.h"
#include <QMainWindow>
#include <QString>
#include <boost/function.hpp>

namespace Ui {
    class MainWindow;
}

class MainWindow : public QMainWindow
{
    Q_OBJECT

    typedef boost::function<QString(QString)> callback_t;
    Ui::MainWindow *ui;
    callback_t callback;

public:
    explicit MainWindow(callback_t cb, QWidget *parent = 0) :
        QMainWindow(parent),
        ui(new Ui::MainWindow),
        callback(cb) {
            ui->setupUi(this);
    }

    ~MainWindow(){
        delete ui;
    }
    

private slots:
    void on_go_button_clicked(){
        ui->textBrowser->setPlainText(callback(this->ui->query_input->text()));
    }
};


